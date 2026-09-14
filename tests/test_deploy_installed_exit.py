"""Execute deployment process guards with in-memory process mocks, never real processes."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

class InstalledExitGuardTest(unittest.TestCase):
    def test_exact_directory_names_and_pid_revalidation(self):
        shell = shutil.which('powershell') or shutil.which('pwsh')
        if not shell:
            self.skipTest('PowerShell behavior verified by Windows CI')
        root = Path(__file__).resolve().parents[1]
        script = r'''
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Deployment PowerShell syntax failed' }
foreach ($name in @('Test-IsInstalledAppProcess','Stop-InstalledAppProcesses')) {
  $fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
  if (-not $fn) { throw ('Missing tested function: '+$name) }
  Invoke-Expression $fn.Extent.Text
}
$installDir='C:\album-owned'
$allowedAppNames=@('album_server.exe','工程影像管理平台.exe')
function Fixture($id,$path,$stamp=1) {
  [pscustomobject]@{ ProcessId=$id; ExecutablePath=$path; CreationDate=$stamp; Name=[IO.Path]::GetFileName($path) }
}
$script:fixtures=@((Fixture 901 'C:\album-owned\工程影像管理平台.exe'),(Fixture 902 'C:\album-owned\album_server.exe'),(Fixture 903 'C:\different-app\album_server.exe'),(Fixture 904 'C:\album-owned-copy\album_server.exe'),(Fixture 905 'C:\album-owned\python.exe'))
$script:stopped=@(); $script:reused=$false
function Get-CimInstance {
  param($ClassName,$Filter,$ErrorAction)
  if ($Filter) {
    $id=[int]($Filter -replace '\D','')
    if ($script:reused -and $id -eq 901) { return Fixture 901 'C:\different-app\album_server.exe' 99 }
    return @($script:fixtures | Where-Object {$_.ProcessId -eq $id})
  }
  return $script:fixtures
}
function Stop-Process {
  param($Id,[switch]$Force,$ErrorAction)
  $script:stopped+=@($Id)
  $script:fixtures=@($script:fixtures | Where-Object {$_.ProcessId -ne $Id})
}
Stop-InstalledAppProcesses
if (($script:stopped -join ',') -ne '901,902') { throw ('Closed unexpected process: '+($script:stopped -join ',')) }
if (($script:fixtures.ProcessId -join ',') -ne '903,904,905') { throw 'Foreign process affected' }
$script:fixtures=@((Fixture 901 'C:\album-owned\album_server.exe'))
$script:stopped=@(); $script:reused=$true
$blocked=$false
try { Stop-InstalledAppProcesses } catch { $blocked=$true }
if (-not $blocked -or $script:stopped.Count) { throw 'Reused PID was not rejected' }
$script:fixtures=@(); $script:reused=$false
Stop-InstalledAppProcesses
if ($script:stopped.Count) { throw 'Empty inventory caused a stop' }
Write-Output 'EXACT_DIRECTORY_AND_PID_REUSE_GUARDS_PASSED'
'''
        with tempfile.TemporaryDirectory(prefix='album-deploy-test-') as tmp:
            path=Path(tmp)/'test.ps1'; path.write_text(script,encoding='utf-8-sig')
            result=subprocess.run([shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(path),str(root/'deploy_prod.ps1')],capture_output=True,text=True,timeout=45,errors='replace')
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        self.assertIn('EXACT_DIRECTORY_AND_PID_REUSE_GUARDS_PASSED',result.stdout)

if __name__=='__main__': unittest.main()
