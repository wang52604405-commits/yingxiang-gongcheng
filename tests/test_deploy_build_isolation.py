"""Build dependencies stay in a fresh venv, never the production/base Python."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy_prod.ps1"


class DesktopBuildIsolationTest(unittest.TestCase):
    def run_command(self, command, **kwargs):
        environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=environment, timeout=90, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        return result.stdout.strip()

    @staticmethod
    def interpreter(root):
        return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    @staticmethod
    def metadata_bytes(site):
        return {str(path.relative_to(site)): path.read_bytes() for path in site.rglob("*") if path.is_file()}

    def test_offline_build_install_keeps_base_metadata_and_packages_isolated(self):
        with tempfile.TemporaryDirectory(prefix="album-build-isolation-") as directory:
            root = Path(directory)
            base_root = root / "base"
            self.run_command([sys.executable, "-I", "-m", "venv", "--without-pip", "--copies", str(base_root)])
            base_python = self.interpreter(base_root)
            base_site = Path(self.run_command([str(base_python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"]))
            fixture = base_site / "album_base_only_fixture-7.0.dist-info"
            fixture.mkdir()
            (fixture / "METADATA").write_text("Metadata-Version: 2.1\nName: album-base-only-fixture\nVersion: 7.0\n", encoding="utf-8")
            (base_site / "album_base_only_fixture.py").write_text("VALUE = 'preserve base package'\n", encoding="utf-8")
            before = self.metadata_bytes(base_site)

            shell = shutil.which("powershell") or shutil.which("pwsh")
            if shell and os.name == "nt":
                # Execute the exact deployed helper, including its config/prefix
                # guards. It creates a venv and seeds pip offline via ensurepip.
                script = root / "prepare-build.ps1"
                script.write_text(r'''
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'PowerShell syntax failed' }
$fn=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Prepare-IsolatedBuildPython'},$true)
if (-not $fn) { throw 'Build helper missing' }
Invoke-Expression $fn.Extent.Text
$installDir=Join-Path $args[2] 'production-app'
$dataDir=Join-Path $args[2] 'production-data'
$build=Prepare-IsolatedBuildPython $args[1] $args[2]
# A temporary directory lexically outside protected roots can still be a
# junction into one of them. Reject it before it creates any venv files.
$junction=Join-Path $args[2] 'linked-temp'
New-Item -ItemType Directory -Path $dataDir | Out-Null
New-Item -ItemType Junction -Path $junction -Target $dataDir | Out-Null
$blocked=$false
try { Prepare-IsolatedBuildPython $args[1] $junction | Out-Null } catch { $blocked=$true }
if (-not $blocked) { throw 'A junction into business data was accepted' }
if (@(Get-ChildItem -LiteralPath $dataDir -Force).Count) { throw 'Business data directory was modified' }
Write-Output $build
''', encoding="utf-8-sig")
                output = self.run_command([shell, "-NoProfile", "-NonInteractive", "-File", str(script), str(DEPLOY), str(base_python), str(root)])
                build_python = Path(output.splitlines()[-1])
                build_root = build_python.parent.parent
            else:
                # Linux exercises the same stdlib venv flags and real package
                # isolation. Windows CI additionally executes the PS helper.
                build_root = root / "build"
                self.run_command([str(base_python), "-I", "-m", "venv", "--copies", str(build_root)])
                build_python = self.interpreter(build_root)
            isolation = self.run_command([str(build_python), "-I", "-c", (
                "import importlib.util,json,site,sys; "
                "print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
                "'user_site':site.ENABLE_USER_SITE,'base_visible':importlib.util.find_spec('album_base_only_fixture') is not None}))"
            )])
            state = json.loads(isolation)
            self.assertNotEqual(state["prefix"], state["base_prefix"])
            self.assertFalse(state["user_site"])
            self.assertFalse(state["base_visible"])
            self.assertIn("include-system-site-packages = false", (build_root / "pyvenv.cfg").read_text(encoding="utf-8").lower())

            wheel = root / "album_build_only_fixture-1.0-py3-none-any.whl"
            contents = {
                "album_build_only_fixture.py": "VALUE = 'build environment only'\n",
                "album_build_only_fixture-1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: album-build-only-fixture\nVersion: 1.0\n",
                "album_build_only_fixture-1.0.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: album-offline-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            }
            record_name = "album_build_only_fixture-1.0.dist-info/RECORD"
            contents[record_name] = "".join(f"{name},,\n" for name in [*contents, record_name])
            with zipfile.ZipFile(wheel, "w") as archive:
                for name, value in contents.items():
                    archive.writestr(name, value)
            self.run_command([
                str(build_python), "-I", "-m", "pip", "--isolated", "install", "--no-index", "--no-deps",
                "--no-user", "--prefix", str(build_root), str(wheel),
            ])
            version = self.run_command([str(build_python), "-I", "-c", "import importlib.metadata; print(importlib.metadata.version('album-build-only-fixture'))"])
            self.assertEqual(version, "1.0")
            base_visibility = self.run_command([str(base_python), "-I", "-c", "import importlib.util; print(importlib.util.find_spec('album_build_only_fixture') is None)"])
            self.assertEqual(base_visibility, "True")
            self.assertEqual(self.metadata_bytes(base_site), before)

    def test_every_dependency_build_and_sign_command_routes_to_isolated_python(self):
        source = DEPLOY.read_text(encoding="utf-8-sig")
        start = source.index("# ---------- 1.")
        end = source.index("# ---------- 5.", start)
        build = source[start:end]
        invocations = [line.strip() for line in build.splitlines() if line.strip().startswith("& ")]
        self.assertEqual(len(invocations), 5)
        self.assertTrue(all(line.startswith("& $buildPythonPath -I ") for line in invocations), invocations)
        pip_invocations = [line for line in invocations if "-m pip " in line]
        self.assertEqual(len(pip_invocations), 2)
        for invocation in pip_invocations:
            self.assertIn("--isolated install --no-user --prefix $buildEnvironmentRoot", invocation)
        self.assertIn("if ($LASTEXITCODE -ne 0)", build.split(pip_invocations[0], 1)[1].split(pip_invocations[1], 1)[0])
        self.assertIn("$basePythonPath = $pythonPath", source)
        self.assertIn("Test-IsVerifiedLegacySourceAppProcess $owner $pythonPath", source)
        self.assertNotIn("& $pythonPath", build)


if __name__ == "__main__":
    unittest.main()
