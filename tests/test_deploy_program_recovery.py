"""Program recovery orchestration: extracted PowerShell, mocked Windows operations."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy_prod.ps1"


class DesktopProgramRecoveryTest(unittest.TestCase):
    def test_snapshot_precedes_stops_and_recovery_only_switches_programs(self):
        source = DEPLOY.read_text(encoding="utf-8-sig")
        main = source[source.index("# ---------- 5."):]
        sequence = [
            "Assert-LegacySourceAutostartDisabled", "Assert-ProgramIntegrity $installDir",
            "$previousVersion = Get-InstalledServiceVersion", 'Invoke-ProgramSnapshotAction "create"',
            'Invoke-ProgramSnapshotAction "verify"', 'Assert-ProgramIntegrity (Join-Path $snapshotPath "program")',
            "$publisherLock = Lock-ProgramPublisher", "$null = Get-InstalledServiceVersion $previousVersion",
            "Invoke-ProgramReplacement $snapshotPath $previousVersion", "$publisherLock.Dispose()",
        ]
        offsets = [main.index(item) for item in sequence]
        self.assertEqual(offsets, sorted(offsets))
        transaction = re.search(r"(?ms)^function Invoke-ProgramReplacement\b.*?^}", source).group()
        self.assertEqual(transaction.count("New-DeploymentPortGuard"), 2)
        recovery = transaction[transaction.index("$releaseFailure ="):]
        sequence = ["Stop-InstalledAppProcessesAndWait", "Get-DeploymentListenerPids", "New-DeploymentPortGuard",
                    'Invoke-ProgramSnapshotAction "verify"', 'Assert-ProgramIntegrity (Join-Path $snapshotPath "program")',
                    'Invoke-ProgramSnapshotAction "restore"', "Assert-ProgramIntegrity $installDir", "$portGuard.Stop()",
                    "Start-InstalledProgram", "Wait-InstalledServiceVersion $previousVersion"]
        offsets = []
        position = 0
        for item in sequence:
            position = recovery.index(item, position)
            offsets.append(position)
        self.assertEqual(offsets, sorted(offsets))
        self.assertNotIn("Remove-Item", source)
        self.assertNotIn(".bak-$stamp", source)
        self.assertIn("--replacement-root", source)
        self.assertIn("[IO.FileShare]::None", source)
        self.assertIn("[IO.FileMode]::OpenOrCreate", source)
        self.assertIn("-I -X utf8", source)

    def test_preflight_failure_and_every_update_phase_have_safe_outcomes(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            self.skipTest("Mocked PowerShell orchestration runs on Windows CI")
        script = r'''
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ('PowerShell syntax: '+($errors -join ';')) }
foreach ($name in @('Invoke-ProgramReplacement')) {
  $fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
  Invoke-Expression $fn.Extent.Text
}
$realTransaction=${function:Invoke-ProgramReplacement}
$installDir=Join-Path $args[1] 'owned-program'
$dataDir=Join-Path $args[1] 'business-data'
$expectedVersion='NEW'; $port=5088
$script:checks=0
$script:business=@{photo='new-after-release';sync='latest-confirmed-id';license='existing-license'}
$businessBefore=ConvertTo-Json -Compress -InputObject $script:business
function Reset-Fixtures {
  $script:events=New-Object 'System.Collections.Generic.List[string]'
  $script:failure=''; $script:readCount=0; $script:startCount=0; $script:guardCount=0; $script:foreign=$false
}
function Record($name) {
  $script:events.Add($name)
  if ($script:failure -eq $name) { $script:failure=''; throw ('simulated '+$name) }
}
function Fake-Handle($label) {
  $handle=[pscustomobject]@{Label=$label}
  $handle | Add-Member ScriptMethod Stop { Record ('release-'+$this.Label) }
  $handle | Add-Member ScriptMethod Dispose { Record ('dispose-'+$this.Label) }
  return $handle
}
function Assert-LegacySourceAutostartDisabled { Record 'autostart' }
function Assert-NoLegacySourceLauncherProcess { Record 'launcher-read' }
function Assert-ProgramIntegrity($path) {
  if ($path -eq $installDir) { Record 'integrity-installed' } else { Record 'integrity-snapshot' }
}
function Get-InstalledServiceVersion($requiredVersion='') {
  $script:readCount++; Record ('prehealth-'+$script:readCount)
  return 'OLD'
}
function Invoke-ProgramSnapshotAction($action,$snapshotPath,$version) {
  if ($version -ne 'OLD') { throw 'Snapshot version did not bind to old healthy version' }
  Record ('snapshot-'+$action)
}
function Lock-ProgramPublisher($snapshotPath) { Record 'publisher-lock'; return Fake-Handle 'publisher' }
function Invoke-ProgramReplacement($snapshotPath,$previousVersion) { Record 'transaction' }
$source=Get-Content -LiteralPath $args[0] -Raw -Encoding UTF8
$main=$source.Substring($source.IndexOf('# ---------- 5.'))
foreach ($scenario in @('autostart','integrity-installed','prehealth-1','snapshot-create','snapshot-verify','integrity-snapshot','publisher-lock','prehealth-2')) {
  Reset-Fixtures; $script:failure=$scenario; $blocked=$false
  try { Invoke-Expression $main } catch { $blocked=$true }
  if (-not $blocked -or $script:events.Contains('transaction')) { throw ('Preflight stopped programs: '+$scenario) }
  if ($scenario -eq 'prehealth-2' -and -not $script:events.Contains('dispose-publisher')) { throw 'Publisher lock leaked on preflight failure' }
  $script:checks++
}
Reset-Fixtures
Invoke-Expression $main
if (-not $script:events.Contains('transaction') -or -not $script:events.Contains('dispose-publisher')) { throw 'Validated path did not enter transaction or release publisher lock' }
$script:checks++
Set-Item Function:\Invoke-ProgramReplacement -Value $realTransaction
function Stop-DeploymentApplication { Record 'stop-forward' }
function Stop-InstalledAppProcessesAndWait { Record 'stop-recovery' }
function New-DeploymentPortGuard {
  $script:guardCount++; Record ('guard-'+$script:guardCount)
  return Fake-Handle ('guard-'+$script:guardCount)
}
function Install-NewProgramFiles($snapshotPath) { Record 'install' }
function Start-InstalledProgram { $script:startCount++; Record ('start-'+$script:startCount) }
function Wait-InstalledServiceVersion($requiredVersion) { Record ('health-'+$requiredVersion); return $requiredVersion }
function Get-DeploymentListenerPids { Record 'port-read'; if ($script:foreign) { return 777 } }
$snapshotPath=Join-Path (Join-Path $installDir '.deployment-snapshots') 'fixture'
Reset-Fixtures
Invoke-ProgramReplacement $snapshotPath 'OLD'
if (-not $script:events.Contains('health-NEW') -or $script:events.Contains('snapshot-restore')) { throw 'Successful new version incorrectly restored old program' }
$script:checks++
foreach ($scenario in @('stop-forward','guard-1','install','release-guard-1','start-1','health-NEW')) {
  Reset-Fixtures; $script:failure=$scenario; $message=''
  try { Invoke-ProgramReplacement $snapshotPath 'OLD' } catch { $message=$_.Exception.Message }
  # A release always remains failed, even after verified recovery.
  if (-not $message -or $message -notlike '*已恢复并核实旧正式程序版本 OLD*') { throw ('Recovery not confirmed for '+$scenario+': '+$message) }
  if (-not $script:events.Contains('snapshot-restore') -or -not $script:events.Contains('health-OLD')) { throw ('Missing restore/old health for '+$scenario) }
  $restore=$script:events.IndexOf('snapshot-restore')
  $guard=$script:events.IndexOf('guard-'+$script:guardCount)
  $release=$script:events.LastIndexOf('release-guard-'+$script:guardCount)
  if ($guard -gt $restore -or $release -lt $restore) { throw 'Recovery files switched without held port guard' }
  $script:checks++
}
foreach ($scenario in @('stop-recovery','snapshot-verify','integrity-snapshot','snapshot-restore','integrity-installed','health-OLD','guard-2')) {
  Reset-Fixtures; $script:failure=$scenario
  # Fail new health first; the selected failure is applied during recovery.
  function Wait-InstalledServiceVersion($requiredVersion) {
    if ($requiredVersion -eq 'NEW') { Record 'health-NEW'; throw 'new health failed' }
    Record ('health-'+$requiredVersion); return $requiredVersion
  }
  $message=''
  try { Invoke-ProgramReplacement $snapshotPath 'OLD' } catch { $message=$_.Exception.Message }
  if ($message -notlike '*恢复未确认*' -or $message -like '*已恢复并核实旧正式程序版本*') { throw ('Recovery failure claimed success: '+$scenario+': '+$message) }
  $script:checks++
}
Reset-Fixtures; $script:foreign=$true; $message=''
try { Invoke-ProgramReplacement $snapshotPath 'OLD' } catch { $message=$_.Exception.Message }
if ($message -notlike '*恢复未确认*' -or $script:events.Contains('snapshot-restore')) { throw 'Foreign listener was ignored during recovery' }
if ((ConvertTo-Json -Compress -InputObject $script:business) -cne $businessBefore) { throw 'Recovery changed business data, sync state or license' }
Write-Output ('PROGRAM_RECOVERY_ORCHESTRATION_PASSED checks='+$script:checks)
'''
        self.run_powershell(shell, script, "PROGRAM_RECOVERY_ORCHESTRATION_PASSED")

    def test_health_identity_launch_payload_and_exclusive_publisher_lock(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            self.skipTest("Mocked PowerShell health/launch/lock runs on Windows CI")
        script = r'''
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'PowerShell deployment syntax failed' }
foreach ($name in @('Test-IsInstalledAppProcess','Get-InstalledServiceVersion','Start-InstalledProgram','Lock-ProgramPublisher')) {
  $fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
  Invoke-Expression $fn.Extent.Text
}
$script:fixtureRoot=$args[1]
# Match production startup normalization. Windows PowerShell/.NET Framework
# may expand the runner's short (RUNNER~1) temporary-directory prefix here.
$installDir=[IO.Path]::GetFullPath((Join-Path $script:fixtureRoot 'owned-program')).TrimEnd([char[]]'\/')
$dataDir=Join-Path $script:fixtureRoot '业务资料 & keep'
$port=5088; $allowedAppNames=@('album_server.exe','工程影像管理平台.exe')
function Reset-Health {
  $script:version='OLD'; $script:status=200; $script:ok=$true; $script:pidReads=0; $script:processReads=0
  $script:wrongPath=$false; $script:reused=$false; $script:changedListener=$false; $script:noVersion=$false; $script:noStamp=$false
}
function Get-DeploymentListenerPids {
  $script:pidReads++
  if ($script:changedListener -and $script:pidReads -gt 1) { return 902 }
  return 901
}
function Get-CimInstance {
  param($ClassName,$Filter,$ErrorAction)
  $script:processReads++
  $path=Join-Path $installDir 'album_server.exe'
  if ($script:wrongPath) { $path=Join-Path (Join-Path $script:fixtureRoot 'foreign-program') 'album_server.exe' }
  $stamp=1
  if ($script:reused -and $script:processReads -gt 1) { $stamp=2 }
  if ($script:noStamp) { $stamp=$null }
  return [pscustomobject]@{ProcessId=901;ExecutablePath=$path;CreationDate=$stamp}
}
function Invoke-WebRequest {
  param($Uri,[switch]$UseBasicParsing,$TimeoutSec)
  $version=$script:version
  if ($script:noVersion) { $version='' }
  return [pscustomobject]@{StatusCode=$script:status;Content=(ConvertTo-Json -Compress -InputObject @{ok=$script:ok;app_version=$version})}
}
Reset-Health
$healthyOwner=Get-CimInstance Win32_Process -Filter 'ProcessId=901' -ErrorAction Stop
if (-not (Test-IsInstalledAppProcess $healthyOwner)) {
  $canonicalExecutable=[IO.Path]::GetFullPath([string]$healthyOwner.ExecutablePath)
  $canonicalDirectory=[IO.Path]::GetDirectoryName($canonicalExecutable).TrimEnd([char[]]'\/')
  throw ('Healthy fixture ownership mismatch: install='+$installDir+' executable='+$canonicalExecutable+' directory='+$canonicalDirectory+' stamp='+$healthyOwner.CreationDate)
}
Reset-Health
if ((Get-InstalledServiceVersion 'OLD') -cne 'OLD') { throw 'Healthy installed service rejected' }
foreach ($case in @('wrong-version','wrong-path','pid-reused','listener-changed','missing-version','missing-stamp','bad-http','not-ok')) {
  Reset-Health
  switch ($case) {
    'wrong-version' {$script:version='WRONG'}
    'wrong-path' {$script:wrongPath=$true}
    'pid-reused' {$script:reused=$true}
    'listener-changed' {$script:changedListener=$true}
    'missing-version' {$script:noVersion=$true}
    'missing-stamp' {$script:noStamp=$true}
    'bad-http' {$script:status=503}
    'not-ok' {$script:ok=$false}
  }
  $blocked=$false
  try { Get-InstalledServiceVersion 'OLD' | Out-Null } catch { $blocked=$true }
  if (-not $blocked) { throw ('Unsafe health accepted: '+$case) }
}
# Inspect detached launch data without invoking any real Windows process.
$script:launchCommand=$null
function Invoke-CimMethod {
  param($ClassName,$MethodName,$Arguments)
  $script:launchCommand=$Arguments.CommandLine
  if ($Arguments.CurrentDirectory -cne $installDir) { throw 'Wrong installed working directory' }
  return [pscustomobject]@{ReturnValue=0}
}
$savedUser=$env:ALBUM_CLOUD_AUTO_USER; $savedPass=$env:ALBUM_CLOUD_AUTO_PASS
try {
  $env:ALBUM_CLOUD_AUTO_USER='user & literal'
  $env:ALBUM_CLOUD_AUTO_PASS='pass" & echo SHOULD_NOT_EXECUTE'
  Start-InstalledProgram
  if ($script:launchCommand -notmatch '-EncodedCommand ([A-Za-z0-9+/=]+)$') { throw 'Unsafe detached launch command' }
  $launcher=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($Matches[1]))
  if ($launcher -notmatch "FromBase64String\('([A-Za-z0-9+/=]+)'\)") { throw 'Launch payload missing' }
  $payload=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Matches[1])) | ConvertFrom-Json
  if ($payload.dataDir -cne $dataDir -or $payload.cloudPass -cne $env:ALBUM_CLOUD_AUTO_PASS -or $payload.licenseFile -cne (Join-Path $installDir 'license.dat')) { throw 'Runtime paths or literal credentials changed' }
} finally { $env:ALBUM_CLOUD_AUTO_USER=$savedUser; $env:ALBUM_CLOUD_AUTO_PASS=$savedPass }
# FileShare.None excludes a second publisher and never truncates lock evidence.
$snapshot=Join-Path (Join-Path $args[1] '.deployment-snapshots') 'snapshot'
New-Item -ItemType Directory -Path $snapshot | Out-Null
$lockFile=Join-Path (Split-Path $snapshot -Parent) 'publisher.lock'
[IO.File]::WriteAllText($lockFile,'retain lock evidence')
$first=Lock-ProgramPublisher $snapshot
$blocked=$false
try { $second=Lock-ProgramPublisher $snapshot; $second.Dispose() } catch { $blocked=$true }
if (-not $blocked) { throw 'Concurrent publisher lock was accepted' }
$first.Dispose()
$third=Lock-ProgramPublisher $snapshot; $third.Dispose()
if ([IO.File]::ReadAllText($lockFile) -cne 'retain lock evidence') { throw 'Publisher lock evidence truncated' }
Write-Output 'PROGRAM_HEALTH_LAUNCH_LOCK_PASSED'
'''
        self.run_powershell(shell, script, "PROGRAM_HEALTH_LAUNCH_LOCK_PASSED")

    def run_powershell(self, shell, script, marker):
        with tempfile.TemporaryDirectory(prefix="album-program-recovery-test-") as tmp:
            path = Path(tmp) / "test.ps1"
            path.write_text(script, encoding="utf-8-sig")
            result = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path), str(DEPLOY), tmp],
                capture_output=True, text=True, timeout=60, errors="replace",
            )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn(marker, result.stdout)


if __name__ == "__main__":
    unittest.main()
