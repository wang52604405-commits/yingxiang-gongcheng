"""Read-only Windows autostart preflight; behavior uses in-memory inventories only."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy_prod.ps1"


class AutostartPreflightTest(unittest.TestCase):
    def test_preflight_is_read_only_and_precedes_application_changes(self):
        source = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertNotIn("Disable-LegacySourceAutostart", source)
        self.assertNotIn("SetEnvironmentVariable", source)
        self.assertNotRegex(source, r"(?im)^\s*\$env:ALBUM_ENABLE_SOURCE_AUTOSTART\s*=")
        for name in (
            "Get-LegacySourceAutostartEnvironmentValue",
            "Assert-NoLegacySourceLauncherProcess",
            "Assert-LegacySourceAutostartDisabled",
        ):
            match = re.search(r"(?ms)^function " + re.escape(name) + r"\b.*?^}", source)
            self.assertIsNotNone(match, name)
            body = match.group()
            self.assertNotRegex(body, r"(?i)\b(?:Remove|Set|New|Stop|Disable|Unregister|Register)-[A-Za-z]+")
            self.assertNotIn("SilentlyContinue", body)
        for command in ("Remove-ItemProperty", "Stop-ScheduledTask", "Disable-ScheduledTask"):
            self.assertNotIn(command, source)
        self.assertNotRegex(source, r"Stop-Process[^\n]*\$parent\.")
        main = source[source.index("# ---------- 5."):]
        call = main.index("\nAssert-LegacySourceAutostartDisabled\n")
        self.assertLess(call, main.index('Invoke-ProgramSnapshotAction "create"'))
        self.assertLess(call, main.index("Invoke-ProgramReplacement "))
        self.assertLess(call, main.index("# ---------- 6."))
        self.assertRegex(source, r"do \{\s+Assert-NoLegacySourceLauncherProcess\s+\$listenerPids")
        self.assertRegex(source, r"for \(\$i = 0; \$i -lt 30; \$i\+\+\) \{\s+Assert-NoLegacySourceLauncherProcess")

    def test_unsafe_or_unreadable_inventory_blocks_without_mutation(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            self.skipTest("PowerShell behavior verified by Windows CI")
        script = r'''
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Deployment PowerShell syntax failed' }
foreach ($name in @('Test-IsLegacySourceLauncherText','Get-SafeProcessCommandLine','Get-LegacySourceAutostartEnvironmentValue','Assert-NoLegacySourceLauncherProcess','Assert-LegacySourceAutostartDisabled')) {
  $fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
  if (-not $fn) { throw ('Missing tested function: '+$name) }
  Invoke-Expression $fn.Extent.Text
}
$cu='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$lm='HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
$script:mutations=0; $script:checks=0
function Reset-Fixtures {
  $script:values=@{Process='0';User='0'}
  $script:runs=@{}
  $script:runs[$cu]=[pscustomobject]@{Formal='"C:\album-owned\工程影像管理平台.exe"';Other='"C:\other\app.exe"'}
  $script:runs[$lm]=[pscustomobject]@{}
  $script:tasks=@([pscustomobject]@{TaskName='Formal';State='Ready';Actions=@([pscustomobject]@{Execute='C:\album-owned\工程影像管理平台.exe';Arguments='';WorkingDirectory='C:\album-owned'})})
  $script:processes=@([pscustomobject]@{ProcessId=901;Name='album_server.exe';CommandLine='"C:\album-owned\album_server.exe"'})
  $script:failedRead=''
}
function Get-LegacySourceAutostartEnvironmentValue {
  param($target)
  if ($script:failedRead -eq ('env'+$target)) { throw 'Environment read denied' }
  return $script:values[$target]
}
function Test-Path {
  param($LiteralPath,$ErrorAction)
  if ($ErrorAction -ne 'Stop') { throw 'Run existence check must terminate on error' }
  if ($script:failedRead -eq 'run-path') { throw 'Run existence read denied' }
  return $script:runs.ContainsKey($LiteralPath)
}
function Get-ItemProperty {
  param($LiteralPath,$ErrorAction)
  if ($ErrorAction -ne 'Stop') { throw 'Run read must terminate on error' }
  if ($script:failedRead -eq 'run') { throw 'Run read denied' }
  if ($script:failedRead -eq 'run-null') { return $null }
  return $script:runs[$LiteralPath]
}
function Get-ScheduledTask {
  param($ErrorAction)
  if ($ErrorAction -ne 'Stop') { throw 'Task read must terminate on error' }
  if ($script:failedRead -eq 'tasks') { throw 'Task read denied' }
  return $script:tasks
}
function Get-CimInstance {
  param($ClassName,$ErrorAction)
  if ($ClassName -ne 'Win32_Process' -or $ErrorAction -ne 'Stop') { throw 'Unsafe process inventory' }
  if ($script:failedRead -eq 'processes') { throw 'Process read denied' }
  return $script:processes
}
function Remove-ItemProperty { $script:mutations++; throw 'Registry mutation forbidden' }
function Set-ItemProperty { $script:mutations++; throw 'Registry mutation forbidden' }
function Stop-ScheduledTask { $script:mutations++; throw 'Task mutation forbidden' }
function Disable-ScheduledTask { $script:mutations++; throw 'Task mutation forbidden' }
function Stop-Process { $script:mutations++; throw 'Process mutation forbidden' }
function Inventory-State {
  return (ConvertTo-Json -Depth 12 -Compress -InputObject @($script:values,$script:runs,$script:tasks,$script:processes))
}
function Check-Guard($label,$reject) {
  $before=Inventory-State
  $blocked=$false
  try { Assert-LegacySourceAutostartDisabled } catch { $blocked=$true }
  if ($blocked -ne $reject) { throw ('Unexpected preflight outcome: '+$label) }
  if ((Inventory-State) -cne $before -or $script:mutations) { throw ('Inventory changed: '+$label) }
  $script:checks++
}
Reset-Fixtures
Check-Guard 'formal installed autostart remains unchanged' $false
$script:runs.Remove($lm)
Check-Guard 'absent Run key is not an inspection error' $false
foreach ($target in @('Process','User')) {
  foreach ($value in @($null,'','1','true',' 0 ')) {
    Reset-Fixtures; $script:values[$target]=$value
    Check-Guard ('unsafe '+$target+' environment') $true
  }
}
foreach ($path in @($cu,$lm)) {
  foreach ($launcher in @('"C:\old\AUTOSTART_ALBUM.PS1"','cmd /c "C:\old\start_album.bat"')) {
    Reset-Fixtures
    $script:runs[$path]=[pscustomobject]@{PSLegacy=$launcher;Formal='"C:\album-owned\工程影像管理平台.exe"'}
    Check-Guard 'historical Run launcher blocks even when value name starts PS' $true
  }
}
foreach ($action in @(
  [pscustomobject]@{Execute='C:\old\autostart_album.ps1';Arguments='';WorkingDirectory='C:\old'},
  [pscustomobject]@{Execute='cmd.exe';Arguments='/c "C:\old\start_album.bat"';WorkingDirectory='C:\old'}
)) {
  Reset-Fixtures
  $script:tasks=@([pscustomobject]@{TaskName='Old';State='Disabled';Actions=@($action)})
  Check-Guard 'historical task blocks even when disabled' $true
}
foreach ($failure in @('envProcess','envUser','run-path','run','run-null','tasks','processes')) {
  Reset-Fixtures; $script:failedRead=$failure
  Check-Guard ('unreadable '+$failure) $true
}
Reset-Fixtures
$script:processes+=@([pscustomobject]@{ProcessId=902;Name='powershell.exe';CommandLine='powershell -File "C:\old\autostart_album.ps1"'})
Check-Guard 'running historical launcher blocks without killing' $true
Reset-Fixtures
$script:runs[$cu]=[pscustomobject]@{Formal='"C:\album-owned\工程影像管理平台.exe"';Backup='"C:\old\autostart_album.ps1.bak"'}
Check-Guard 'similar backup filename is not a launcher' $false
# A launcher appearing after the main preflight is rejected by the loop guard.
$script:processes+=@([pscustomobject]@{ProcessId=903;Name='cmd.exe';CommandLine='cmd /c "C:\old\start_album.bat"'})
$before=Inventory-State; $blocked=$false
try { Assert-NoLegacySourceLauncherProcess } catch { $blocked=$true }
if (-not $blocked -or (Inventory-State) -cne $before -or $script:mutations) { throw 'Launcher race did not fail closed' }
# A parent launcher appearing after the inventory read must not be stopped,
# even when the listening Python instance has the verified product signature.
$branch=$ast.Find({param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text.StartsWith('if (Test-IsVerifiedLegacySourceAppProcess ')},$true)
if (-not $branch) { throw 'Missing verified source listener branch' }
function Test-IsVerifiedLegacySourceAppProcess { return $true }
function Get-CimInstance {
  param($ClassName,$Filter,$ErrorAction)
  return [pscustomobject]@{ProcessId=904;Name='cmd.exe';CommandLine='cmd /c "C:\old\start_album.bat"'}
}
$owner=[pscustomobject]@{ParentProcessId=904;Name='python.exe'}
$listenerPid=905; $pythonPath='C:\python\python.exe'; $expectedVersion='test'; $port=5088
$blocked=$false
try { Invoke-Expression $branch.Extent.Text } catch { $blocked=$true }
if (-not $blocked -or $script:mutations) { throw 'Legacy parent or child was stopped after an inventory race' }
if ($script:checks -lt 25) { throw 'Autostart scenario coverage incomplete' }
Write-Output ('READ_ONLY_AUTOSTART_PREFLIGHT_PASSED checks='+$script:checks)
'''
        with tempfile.TemporaryDirectory(prefix="album-autostart-test-") as tmp:
            path = Path(tmp) / "test.ps1"
            path.write_text(script, encoding="utf-8-sig")
            result = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path), str(SCRIPT)],
                capture_output=True, text=True, timeout=45, errors="replace",
            )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("READ_ONLY_AUTOSTART_PREFLIGHT_PASSED", result.stdout)


if __name__ == "__main__":
    unittest.main()
