"""Real Windows GUI child launch with inherited native stdout/stderr handles."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows GUI launch integration")
class GuiLaunchIntegrationTest(unittest.TestCase):
    def test_real_detached_gui_launch_retains_native_streams_and_previous_logs(self):
        shell = shutil.which("powershell")
        self.assertIsNotNone(shell, "Windows PowerShell is required on Windows CI")
        script = r'''
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Deployment script syntax failed' }
$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Start-InstalledProgram'},$true)
if (-not $fn) { throw 'Missing production launch function' }
Invoke-Expression $fn.Extent.Text
$installDir=[IO.Path]::GetFullPath((Join-Path $args[1] 'program & literal'))
$dataDir=Join-Path $args[1] 'fixture-data'
New-Item -ItemType Directory -Path $installDir,$dataDir | Out-Null
$exe=Join-Path $installDir 'album_server.exe'
$code=@"
using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class GuiFixture {
 [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr GetStdHandle(int n);
 static void Main() {
  string data=Environment.GetEnvironmentVariable("ALBUM_DATA_DIR");
  try {
   File.WriteAllText(Path.Combine(data,"pid"), System.Diagnostics.Process.GetCurrentProcess().Id.ToString());
   File.WriteAllLines(Path.Combine(data,"environment"), new string[]{Environment.CurrentDirectory,Environment.GetEnvironmentVariable("ALBUM_LICENSE_FILE"),Environment.GetEnvironmentVariable("ALBUM_CLOUD_AUTO_USER"),Environment.GetEnvironmentVariable("ALBUM_CLOUD_AUTO_PASS")});
   IntPtr o=GetStdHandle(-11), e=GetStdHandle(-12);
   if(o==IntPtr.Zero || o==new IntPtr(-1) || e==IntPtr.Zero || e==new IntPtr(-1)) throw new Exception("Native standard handles are missing");
   using(var output=new StreamWriter(new FileStream(new SafeFileHandle(o,false),FileAccess.Write),new UTF8Encoding(false)))
   using(var error=new StreamWriter(new FileStream(new SafeFileHandle(e,false),FileAccess.Write),new UTF8Encoding(false))) {
    output.WriteLine("NATIVE_STDOUT_READY");output.Flush();
    error.WriteLine("NATIVE_STDERR_READY");error.Flush();
    var listener=new TcpListener(IPAddress.Loopback,int.Parse(Environment.GetEnvironmentVariable("ALBUM_PORT")));
    listener.Start();
    while(true) using(var client=listener.AcceptTcpClient()) using(var stream=client.GetStream()) {
     byte[] request=new byte[4096];stream.Read(request,0,request.Length);
     byte[] response=Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 5\r\nConnection: close\r\n\r\nREADY");
     stream.Write(response,0,response.Length);stream.Flush();
    }
   }
  } catch(Exception ex) { File.WriteAllText(Path.Combine(data,"failure"),ex.ToString()); }
 }
}
"@
# A real WinExe, not a console process or a mocked Start-Process call.
Add-Type -TypeDefinition $code -Language CSharp -OutputAssembly $exe -OutputType WindowsApplication
$socket=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
$socket.Start();$port=$socket.LocalEndpoint.Port;$socket.Stop()
$oldOut=Join-Path $installDir 'server.out.log';$oldErr=Join-Path $installDir 'server.err.log'
[IO.File]::WriteAllText($oldOut,'previous stdout evidence')
[IO.File]::WriteAllText($oldErr,'previous stderr evidence')
$script:payloads=@()
# Observe the real command, then execute the production WMI call unchanged.
function Invoke-CimMethod {
 param($ClassName,$MethodName,$Arguments)
 if ($Arguments.CommandLine -notmatch '-EncodedCommand ([A-Za-z0-9+/=]+)$') { throw 'Missing encoded launcher' }
 $launcher=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($Matches[1]))
 if ($launcher -notmatch "FromBase64String\('([A-Za-z0-9+/=]+)'\)") { throw 'Missing literal JSON payload' }
 $script:payloads+=([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Matches[1]))|ConvertFrom-Json)
 CimCmdlets\Invoke-CimMethod -ClassName $ClassName -MethodName $MethodName -Arguments $Arguments
}
function Stop-Fixture {
 $processes=@(Get-CimInstance Win32_Process -Filter "Name='album_server.exe'" | Where-Object {$_.ExecutablePath -eq $exe})
 foreach($process in $processes) {
  # Revalidate exact executable and creation time before terminating a fixture.
  $current=Get-CimInstance Win32_Process -Filter ('ProcessId='+$process.ProcessId)
  if ($current -and $current.ExecutablePath -eq $exe -and $current.CreationDate -eq $process.CreationDate) {
   Stop-Process -Id $current.ProcessId -Force
   Wait-Process -Id $current.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
  }
 }
}
try {
 $env:ALBUM_CLOUD_AUTO_USER='fixture user & literal'
 $env:ALBUM_CLOUD_AUTO_PASS='fixture " & not a command'
 foreach($attempt in 1..2) {
  Start-InstalledProgram
  $healthy=$false
  for($i=0;$i -lt 30;$i++) {
   Start-Sleep -Milliseconds 200
   if(Test-Path (Join-Path $dataDir 'failure')) { throw [IO.File]::ReadAllText((Join-Path $dataDir 'failure')) }
   try { $response=Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/" -TimeoutSec 1; if($response.Content -eq 'READY'){$healthy=$true;break} } catch {}
  }
  if(-not $healthy) { Stop-Fixture; Get-ChildItem $installDir,$dataDir -File | ForEach-Object { if ($_.Extension -ne '.exe') { Write-Output ($_.FullName+': '+[IO.File]::ReadAllText($_.FullName)) } }; throw 'Real GUI fixture never served its health endpoint' }
  Stop-Fixture
  $payload=$script:payloads[-1]
  if([IO.File]::ReadAllText($payload.outLog) -notmatch 'NATIVE_STDOUT_READY') { throw 'Missing native stdout' }
  if([IO.File]::ReadAllText($payload.errLog) -notmatch 'NATIVE_STDERR_READY') { throw 'Missing native stderr' }
  $environment=[IO.File]::ReadAllLines((Join-Path $dataDir 'environment'))
  if($environment[0] -cne $installDir -or $environment[1] -cne (Join-Path $installDir 'license.dat') -or $environment[2] -cne $env:ALBUM_CLOUD_AUTO_USER -or $environment[3] -cne $env:ALBUM_CLOUD_AUTO_PASS) { throw 'Working directory or literal environment values changed' }
 }
 if($script:payloads[0].outLog -ceq $script:payloads[1].outLog -or $script:payloads[0].errLog -ceq $script:payloads[1].errLog) { throw 'Repeated launch overwrites previous evidence' }
 if([IO.File]::ReadAllText($oldOut) -cne 'previous stdout evidence' -or [IO.File]::ReadAllText($oldErr) -cne 'previous stderr evidence') { throw 'Existing production-style logs were overwritten' }
 foreach($payload in $script:payloads) {
  if([IO.File]::ReadAllText($payload.outLog) -notmatch 'NATIVE_STDOUT_READY' -or [IO.File]::ReadAllText($payload.errLog) -notmatch 'NATIVE_STDERR_READY') { throw 'Earlier launch logs lost after later launch' }
 }
 Write-Output 'REAL_GUI_NATIVE_STREAMS_PASSED'
} finally { Stop-Fixture }
'''
        with tempfile.TemporaryDirectory(prefix="album-gui-launch-test-") as temporary:
            path = Path(temporary) / "probe.ps1"
            path.write_text(script, encoding="utf-8-sig")
            result = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-File", str(path), str(ROOT / "deploy_prod.ps1"), temporary],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("REAL_GUI_NATIVE_STREAMS_PASSED", result.stdout)


if __name__ == "__main__":
    unittest.main()