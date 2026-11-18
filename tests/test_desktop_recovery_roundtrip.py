"""Bridge real PowerShell replacement orchestration and real program-only snapshots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROGRAM_FILES = ("album_server.exe", "工程影像管理平台.exe", "guard_manifest.dat", "_internal/runtime.dll", "_internal/nested/module.bin")


class DesktopRecoveryRoundtripTest(unittest.TestCase):
    def run_case(self, scenario):
        shell = os.environ.get("ALBUM_TEST_POWERSHELL") or shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            self.skipTest("PowerShell orchestration roundtrip runs on Windows CI")
        with tempfile.TemporaryDirectory(prefix="album-program-roundtrip-") as temporary:
            root = Path(temporary)
            install, data, incoming = (root / name for name in ("installed", "business", "incoming"))
            for directory in (install, data, incoming):
                directory.mkdir()
            for version, directory in (("OLD", install), ("NEW", incoming)):
                for name in PROGRAM_FILES:
                    path = directory / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(f"{version}|{name}".encode("utf-8"))
            protected = {
                install / "license.dat": b"existing license bytes",
                install / "operator.txt": b"unknown root file must stay",
                install / "server.out.log": b"existing log must stay",
                data / "original.jpg": b"existing original bytes",
            }
            for path, content in protected.items():
                path.write_bytes(content)
            database = data / "projects.db"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE photos(id INTEGER PRIMARY KEY, title TEXT)")
                connection.execute("INSERT INTO photos VALUES(1, 'before snapshot')")
            mutation = root / "after_snapshot.py"
            mutation.write_text(
                "from pathlib import Path\nimport hashlib,sqlite3,sys\n"
                "data, install = map(Path, sys.argv[1:3])\n"
                "with sqlite3.connect(data/'projects.db') as c:\n"
                "    c.execute(\"INSERT INTO photos VALUES(2, 'after snapshot')\")\n"
                "(data/'after-snapshot.jpg').write_bytes(b'new original after snapshot')\n"
                "(data/'sync-state.json').write_bytes(b'new sync state after snapshot')\n"
                "(install/'sync-state.json').write_bytes(b'new install sync state after snapshot')\n"
                "(data.parent/'database-after-snapshot.sha256').write_text(hashlib.sha256((data/'projects.db').read_bytes()).hexdigest())\n",
                encoding="utf-8",
            )
            script = root / "roundtrip.ps1"
            script.write_text(POWERSHELL, encoding="utf-8-sig")
            snapshot = install / ".deployment-snapshots" / scenario
            result = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                 str(ROOT), sys.executable, str(install), str(data), str(incoming), str(snapshot), str(mutation), scenario],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
            )
            self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
            marker = next((line for line in result.stdout.splitlines() if line.startswith("ROUNDTRIP=")), None)
            self.assertIsNotNone(marker, result.stdout)
            report = json.loads(marker.removeprefix("ROUNDTRIP="))
            self.assertEqual(report["success"], scenario == "success")
            expected_version = "NEW" if scenario == "success" else "OLD"
            for name in PROGRAM_FILES:
                self.assertEqual((install / name).read_bytes(), f"{expected_version}|{name}".encode("utf-8"))
                self.assertEqual((snapshot / "program" / name).read_bytes(), f"OLD|{name}".encode("utf-8"))
            for path, content in protected.items():
                self.assertEqual(path.read_bytes(), content)
            self.assertEqual((data / "after-snapshot.jpg").read_bytes(), b"new original after snapshot")
            self.assertEqual((data / "sync-state.json").read_bytes(), b"new sync state after snapshot")
            self.assertEqual((install / "sync-state.json").read_bytes(), b"new install sync state after snapshot")
            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), (root / "database-after-snapshot.sha256").read_text())
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT * FROM photos ORDER BY id").fetchall(), [(1, "before snapshot"), (2, "after snapshot")])
                self.assertEqual(connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertFalse((snapshot / "program" / "license.dat").exists())
            self.assertFalse((snapshot / "program" / "operator.txt").exists())
            self.assertFalse((snapshot / "program" / "sync-state.json").exists())
            self.assertTrue(list(snapshot.glob("displaced-*")), "real installation must retain displaced program files")
            if scenario != "success":
                self.assertIn("已恢复并核实旧正式程序版本 OLD", report["failure"])
                self.assertTrue(list(snapshot.glob("failed-program-*")), "real restore must retain failed replacement bytes")
                self.assertEqual(report["health"][-1], "OLD")
            else:
                self.assertEqual(report["health"], ["NEW"])

    def test_success_installs_new_program_and_keeps_post_snapshot_business_writes(self):
        self.run_case("success")

    def test_partial_real_copy_failure_restores_old_program_and_keeps_business_writes(self):
        self.run_case("copy-failure")

    def test_start_failure_restores_old_program_and_keeps_business_writes(self):
        self.run_case("start-failure")

    def test_new_health_failure_restores_old_program_and_keeps_business_writes(self):
        self.run_case("health-failure")


POWERSHELL = r'''
param($sourceRoot, $pythonExecutable, $programRoot, $businessRoot, $replacementRoot, $savedRoot, $mutationScript, $scenario)
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $sourceRoot 'deploy_prod.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Deployment PowerShell syntax failed' }
foreach ($name in @('Invoke-ProgramReplacement','Install-NewProgramFiles','Invoke-ProgramSnapshotAction')) {
    $fn=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if (-not $fn) { throw ('Missing real function: '+$name) }
    Invoke-Expression $fn.Extent.Text
}
$repoRoot=$sourceRoot; $basePythonPath=$pythonExecutable
$installDir=$programRoot; $dataDir=$businessRoot; $distDir=$replacementRoot; $expectedVersion='NEW'
$script:starts=0; $script:copies=0; $script:health=@()
function Stop-DeploymentApplication {}
function Stop-InstalledAppProcessesAndWait {}
function Assert-NoLegacySourceLauncherProcess {}
function Get-DeploymentListenerPids { return @() }
function New-DeploymentPortGuard {
    $guard=[pscustomobject]@{}
    $guard | Add-Member -MemberType ScriptMethod -Name Stop -Value {} -PassThru
}
function Assert-ProgramIntegrity($programRoot) {
    $main=[IO.File]::ReadAllText((Join-Path $programRoot 'album_server.exe'))
    $version=($main -split '\|')[0]
    if ($version -notin @('OLD','NEW')) { throw 'Unexpected fixture version' }
    foreach ($name in @('album_server.exe','工程影像管理平台.exe','guard_manifest.dat','_internal/runtime.dll','_internal/nested/module.bin')) {
        if ([IO.File]::ReadAllText((Join-Path $programRoot $name)) -cne ($version+'|'+$name)) { throw ('Fixture integrity failed: '+$name) }
    }
}
function Copy-Item {
    param($LiteralPath,$Destination,[switch]$Recurse,$ErrorAction)
    Microsoft.PowerShell.Management\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Recurse:$Recurse -ErrorAction Stop
    $script:copies++
    if ($scenario -eq 'copy-failure' -and $script:copies -eq 2) { throw 'Injected failure after two real program copies' }
}
function Start-InstalledProgram {
    $script:starts++
    if ($scenario -eq 'start-failure' -and $script:starts -eq 1) { throw 'Injected new program start failure' }
}
function Wait-InstalledServiceVersion($requiredVersion) {
    $script:health+=@($requiredVersion)
    if ($scenario -eq 'health-failure' -and $requiredVersion -eq 'NEW') { throw 'Injected new program health failure' }
    Assert-ProgramIntegrity $installDir
    $actual=([IO.File]::ReadAllText((Join-Path $installDir 'album_server.exe')) -split '\|')[0]
    if ($actual -cne $requiredVersion) { throw 'Health version differs from real installed fixture bytes' }
    return $actual
}
Invoke-ProgramSnapshotAction 'create' $savedRoot 'OLD'
Invoke-ProgramSnapshotAction 'verify' $savedRoot 'OLD'
& $basePythonPath -I $mutationScript $dataDir $installDir
if ($LASTEXITCODE -ne 0) { throw 'Post-snapshot business mutation fixture failed' }
$success=$false; $failure=''
try { Invoke-ProgramReplacement $savedRoot 'OLD'; $success=$true } catch { $failure=$_.Exception.Message }
if (($scenario -eq 'success') -ne $success) { throw ('Unexpected transaction outcome: '+$failure) }
Write-Output ('ROUNDTRIP='+(@{success=$success;failure=$failure;health=@($script:health)} | ConvertTo-Json -Compress))
'''


if __name__ == "__main__":
    unittest.main()
