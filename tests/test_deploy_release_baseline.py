"""Run the real workflow decision with disposable API responses, never production."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "a" * 40
CURRENT = "c" * 40


class SuccessfulReleaseBaselineTest(unittest.TestCase):
    def decide(self, runs, files, *, runs_exit=0, compare_exit=0, event="push", runs_raw=None, compare_raw=None):
        shell = os.environ.get("ALBUM_TEST_POWERSHELL") or shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            self.skipTest("PowerShell workflow decision runs on Windows CI")
        source = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
        start = source.index('          if ("${{ github.event_name }}" -eq "workflow_dispatch")')
        end = source.index("\n      - name: 部署授权中心到阿里云", start)
        decision = textwrap.dedent(source[start:end]).replace("${{ github.event_name }}", event)
        decision = decision.replace("${{ github.repository }}", "fixture/repository")
        stub = r'''
$ErrorActionPreference = 'Stop'
function Start-Sleep { param($Seconds) }
function curl.exe {
  $url = $args[-1]
  [IO.File]::AppendAllText($env:ALBUM_TEST_CALLS, "$url`n")
  $outputIndex = [array]::IndexOf($args, '-o')
  if ($outputIndex -lt 0) { throw 'API output path is missing' }
  if ($url -like '*/actions/runs?*') {
    $global:LASTEXITCODE = [int]$env:ALBUM_TEST_RUNS_EXIT
    if ($LASTEXITCODE -eq 0) { [IO.File]::WriteAllText($args[$outputIndex + 1], $env:ALBUM_TEST_RUNS) }
  } elseif ($url -like '*/compare/*') {
    $global:LASTEXITCODE = [int]$env:ALBUM_TEST_COMPARE_EXIT
    if ($LASTEXITCODE -eq 0) { [IO.File]::WriteAllText($args[$outputIndex + 1], $env:ALBUM_TEST_COMPARE) }
  } else { throw "Unexpected API URL: $url" }
}
'''
        with tempfile.TemporaryDirectory(prefix="release-baseline-") as temporary:
            root = Path(temporary)
            script = root / "decision.ps1"
            script.write_text(stub + "\n" + decision, encoding="utf-8-sig")
            environment = dict(os.environ, RUNNER_TEMP=str(root), GITHUB_RUN_ID="fixture",
                               GITHUB_SHA=CURRENT, GITHUB_TOKEN="fixture-only",
                               GITHUB_OUTPUT=str(root / "output"), ALBUM_TEST_CALLS=str(root / "calls"),
                               ALBUM_TEST_RUNS=json.dumps({"workflow_runs": runs}) if runs_raw is None else runs_raw,
                               ALBUM_TEST_COMPARE=json.dumps({"status": "ahead", "files": files}) if compare_raw is None else compare_raw,
                               ALBUM_TEST_RUNS_EXIT=str(runs_exit), ALBUM_TEST_COMPARE_EXIT=str(compare_exit))
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                    env=environment, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = (root / "output").read_text(encoding="utf-8")
            calls = (root / "calls").read_text(encoding="utf-8") if (root / "calls").exists() else ""
            return output.strip(), calls

    @staticmethod
    def successful():
        return dict(path=".github/workflows/deploy.yml", head_branch="main", status="completed",
                    conclusion="success", head_sha=BASELINE, created_at="2026-11-17T09:00:00Z")

    def test_retry_includes_server_changes_since_last_success_even_when_previous_push_failed(self):
        # Unrelated successful CI must not replace the actual production baseline.
        unrelated = self.successful()
        unrelated.update(path=".github/workflows/mobile-v1-ci.yml", head_sha="b" * 40,
                         created_at="2026-11-18T02:00:00Z")
        failed = self.successful()
        failed.update(conclusion="failure", head_sha="d" * 40, created_at="2026-11-18T01:00:00Z")
        output, calls = self.decide([failed, unrelated, self.successful()], [{"filename": "server/mobile_api.py"}])
        self.assertEqual(output, "run_deploy=true")
        self.assertIn(f"/compare/{BASELINE}...{CURRENT}", calls)
        self.assertNotIn(f"/compare/{'b' * 40}", calls)
        self.assertNotIn(f"/compare/{'d' * 40}", calls)

    def test_latest_success_without_server_changes_can_skip(self):
        older = self.successful()
        older.update(head_sha="e" * 40, created_at="2026-11-16T09:00:00Z")
        output, calls = self.decide([older, self.successful()], [{"filename": "tests/test_manual_rollback.py"}])
        self.assertEqual(output, "run_deploy=false")
        self.assertIn(f"/compare/{BASELINE}...{CURRENT}", calls)

    def test_missing_successful_release_deploys_instead_of_losing_pending_changes(self):
        output, calls = self.decide([], [])
        self.assertEqual(output, "run_deploy=true")
        self.assertNotIn("/compare/", calls)

    def test_baseline_api_failure_deploys_instead_of_skipping(self):
        output, calls = self.decide([], [], runs_exit=22)
        self.assertEqual(output, "run_deploy=true")
        self.assertEqual(calls.count("/actions/runs?"), 3)
        self.assertNotIn("/compare/", calls)

    def test_compare_failure_or_truncated_results_deploy(self):
        for files, exit_code in (([], 22), ([{"filename": "tests/fixture.py"}] * 300, 0)):
            with self.subTest(compare_exit=exit_code):
                output, _ = self.decide([self.successful()], files, compare_exit=exit_code)
                self.assertEqual(output, "run_deploy=true")

    def test_manual_release_still_deploys_without_comparison(self):
        output, calls = self.decide([], [], event="workflow_dispatch")
        self.assertEqual(output, "run_deploy=true")
        self.assertEqual(calls, "")

    def test_malformed_api_responses_deploy_instead_of_skipping(self):
        for options in ({"runs_raw": "invalid JSON"}, {"runs_raw": "{}"},
                        {"compare_raw": "{}"}, {"compare_raw": "invalid JSON"},
                        {"compare_raw": '{"status":"diverged","files":[]}'},
                        {"compare_raw": '{"status":"ahead","files":{}}'},
                        {"compare_raw": '{"status":"ahead","files":"invalid"}'},
                        {"compare_raw": '{"status":"ahead","files":[{}]}'}):
            with self.subTest(options=options):
                output, _ = self.decide([self.successful()], [], **options)
                self.assertEqual(output, "run_deploy=true")

    def test_renamed_server_file_and_packaged_runtime_rules_require_server_deploy(self):
        for file in ({"filename": "removed.py", "previous_filename": "server/old.py"},
                     {"filename": "municipal_rules.py"}, {"filename": "professional_templates.py"},
                     {"filename": "assets/professional_templates.json"}):
            with self.subTest(file=file):
                output, _ = self.decide([self.successful()], [file])
                self.assertEqual(output, "run_deploy=true")


if __name__ == "__main__":
    unittest.main()
