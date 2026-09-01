import os
import shutil
import subprocess
import sys
import winreg
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "工程影像管理平台"
APP_VERSION = "A20260902-2.86"
APP_REG_KEY = r"Software\工程影像管理平台"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\工程影像管理平台"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
INSTALL_DIR_NAME = "工程影像管理平台"
DESKTOP_EXE_NAME = "工程影像管理平台.exe"
SERVER_EXE_NAME = "album_server.exe"
ICON_FILE_NAME = "app_icon.ico"
LICENSE_FILE_NAME = "license.dat"


def default_install_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / INSTALL_DIR_NAME


def default_data_dir():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_REG_KEY) as key:
            existing, _value_type = winreg.QueryValueEx(key, "DataDir")
        if str(existing or "").strip():
            return Path(str(existing)).expanduser()
    except OSError:
        pass
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / APP_TITLE / "data"


def resource_dir():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "installer_payload"
    return Path(__file__).resolve().parent / "installer_payload"


def desktop_dirs():
    dirs = [Path.home() / "Desktop", Path.home() / "桌面"]
    return [path for path in dirs if path.exists()] or [Path.home() / "Desktop"]


def ps_quote(value):
    return str(value).replace("'", "''")


def is_win10_or_newer():
    if sys.platform != "win32":
        return False
    version = sys.getwindowsversion()
    return version.major >= 10


def run_hidden(command, env=None):
    return subprocess.run(
        command,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=env,
    )


def stop_installed_app_processes(target_dir):
    """只关闭目标目录里的本应用；其它程序占用 5088 时拒绝安装。"""
    script = r"""
$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath($env:ALBUM_UPDATE_INSTALL_DIR).TrimEnd([char[]]'\/')
$allowed = @('album_server.exe', '工程影像管理平台.exe')
function Is-Ours($process) {
  try {
    $executable = [string]$process.ExecutablePath
    if (-not $executable) { return $false }
    $full = [IO.Path]::GetFullPath($executable)
    $name = [IO.Path]::GetFileName($full)
    $directory = [IO.Path]::GetDirectoryName($full).TrimEnd([char[]]'\/')
    return (($allowed -contains $name) -and [string]::Equals($directory, $target, [StringComparison]::OrdinalIgnoreCase))
  } catch { return $false }
}
$ours = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { Is-Ours $_ })
$ours | ForEach-Object { Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500
if (@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { Is-Ours $_ }).Count -ne 0) { exit 24 }
$listenerPids = @(Get-NetTCPConnection -LocalPort 5088 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
foreach ($listenerPid in $listenerPids) {
  $owner = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$listenerPid) -ErrorAction SilentlyContinue
  if (-not $owner -or -not (Is-Ours $owner)) { exit 23 }
}
$listenerPids | ForEach-Object { Stop-Process -Id ([int]$_) -Force -ErrorAction SilentlyContinue }
exit 0
"""
    environment = os.environ.copy()
    environment["ALBUM_UPDATE_INSTALL_DIR"] = str(Path(target_dir).resolve())
    result = run_hidden(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        env=environment,
    )
    return int(result.returncode)


def write_reg_value(root, subkey, name, value, value_type=winreg.REG_SZ):
    with winreg.CreateKeyEx(root, subkey, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, value_type, value)


def delete_reg_value(root, subkey, name):
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def create_shortcut(target, icon, workdir):
    script_template = """
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{shortcut}')
$Shortcut.TargetPath = '{target}'
$Shortcut.WorkingDirectory = '{workdir}'
$Shortcut.IconLocation = '{icon}'
$Shortcut.Save()
"""
    for folder in desktop_dirs():
        shortcut = folder / f"{APP_TITLE}.lnk"
        folder.mkdir(parents=True, exist_ok=True)
        script = script_template.format(
            shortcut=ps_quote(shortcut),
            target=ps_quote(target),
            workdir=ps_quote(workdir),
            icon=ps_quote(icon),
        )
        run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])


def write_uninstall_script(target_dir):
    uninstall_path = target_dir / "卸载工程影像管理平台.ps1"
    script = f"""
$ErrorActionPreference = "SilentlyContinue"
Add-Type -AssemblyName System.Windows.Forms
$InstallDir = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd([char[]]'\/')
$DataDir = (Get-ItemProperty -Path 'HKCU:\\{APP_REG_KEY}' -Name 'DataDir' -ErrorAction SilentlyContinue).DataDir
$DesktopNames = @('{APP_TITLE}.lnk')
$choice = [System.Windows.Forms.MessageBox]::Show(
  "卸载会删除程序文件、桌面快捷方式、开机启动和注册表信息。`n`n是否同时删除数据目录？`n`n选择“是”：删除数据目录`n选择“否”：保留数据目录`n选择“取消”：不卸载",
  "确认卸载",
  [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
  [System.Windows.Forms.MessageBoxIcon]::Question
)
if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) {{ exit 0 }}
$AllowedNames = @('{SERVER_EXE_NAME}', '{DESKTOP_EXE_NAME}')
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {{
  try {{
    $Executable = [IO.Path]::GetFullPath([string]$_.ExecutablePath)
    $Directory = [IO.Path]::GetDirectoryName($Executable).TrimEnd([char[]]'\/')
    ($AllowedNames -contains [IO.Path]::GetFileName($Executable)) -and [string]::Equals($Directory, $InstallDir, [StringComparison]::OrdinalIgnoreCase)
  }} catch {{ $false }}
}} | ForEach-Object {{ Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue }}
foreach ($desktop in @([Environment]::GetFolderPath('Desktop'), "$env:USERPROFILE\\桌面")) {{
  foreach ($name in $DesktopNames) {{
    Remove-Item -LiteralPath (Join-Path $desktop $name) -Force -ErrorAction SilentlyContinue
  }}
}}
Remove-ItemProperty -Path 'HKCU:\\{RUN_KEY}' -Name '{APP_TITLE}' -Force -ErrorAction SilentlyContinue
Remove-Item -Path 'HKCU:\\{UNINSTALL_KEY}' -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path 'HKCU:\\{APP_REG_KEY}' -Recurse -Force -ErrorAction SilentlyContinue
netsh advfirewall firewall delete rule name="{APP_TITLE} 5088" | Out-Null
if ($choice -eq [System.Windows.Forms.DialogResult]::Yes -and $DataDir) {{
  Remove-Item -LiteralPath $DataDir -Recurse -Force -ErrorAction SilentlyContinue
}}
Remove-Item -LiteralPath $InstallDir -Recurse -Force
"""
    uninstall_path.write_text(script, encoding="utf-8")
    return uninstall_path


def write_registry(target_dir, data_dir, autostart):
    launcher = target_dir / DESKTOP_EXE_NAME
    uninstall_script = write_uninstall_script(target_dir)
    uninstall_cmd = f'powershell -NoProfile -ExecutionPolicy Bypass -File "{uninstall_script}"'

    write_reg_value(winreg.HKEY_CURRENT_USER, APP_REG_KEY, "InstallDir", str(target_dir))
    write_reg_value(winreg.HKEY_CURRENT_USER, APP_REG_KEY, "DataDir", str(data_dir))
    write_reg_value(winreg.HKEY_CURRENT_USER, APP_REG_KEY, "Version", APP_VERSION)

    write_reg_value(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, "DisplayName", APP_TITLE)
    write_reg_value(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, "DisplayIcon", str(launcher))
    write_reg_value(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, "InstallLocation", str(target_dir))
    write_reg_value(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, "UninstallString", uninstall_cmd)
    write_reg_value(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, "DisplayVersion", APP_VERSION)
    write_reg_value(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, "Publisher", APP_TITLE)

    if autostart:
        write_reg_value(winreg.HKEY_CURRENT_USER, RUN_KEY, APP_TITLE, f'"{launcher}"')
    else:
        delete_reg_value(winreg.HKEY_CURRENT_USER, RUN_KEY, APP_TITLE)


def copy_payload(target_dir, data_dir):
    source = resource_dir()
    required = [DESKTOP_EXE_NAME, SERVER_EXE_NAME, LICENSE_FILE_NAME, ICON_FILE_NAME]
    missing = [name for name in required if not (source / name).exists()]
    if missing:
        raise RuntimeError("安装包缺少文件：" + "、".join(missing))

    target_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in required:
        shutil.copy2(source / name, target_dir / name)


def start_app(target_dir):
    launcher = target_dir / DESKTOP_EXE_NAME
    subprocess.Popen([str(launcher)], cwd=str(target_dir), creationflags=subprocess.CREATE_NO_WINDOW)


class Installer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_TITLE} 安装程序 {APP_VERSION}")
        self.root.geometry("860x520")
        self.root.resizable(False, False)
        self.root.configure(bg="#0d1117")
        self.install_path = tk.StringVar(value=str(default_install_dir()))
        self.data_path = tk.StringVar(value=str(default_data_dir()))
        self.autostart = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="准备安装")
        self.build()

    def browse_install(self):
        selected = filedialog.askdirectory(title="选择安装位置", initialdir=str(Path(self.install_path.get()).parent))
        if selected:
            self.install_path.set(str(Path(selected) / INSTALL_DIR_NAME if Path(selected).name != INSTALL_DIR_NAME else Path(selected)))

    def browse_data(self):
        selected = filedialog.askdirectory(title="选择数据存储位置", initialdir=str(Path(self.data_path.get()).parent))
        if selected:
            self.data_path.set(selected)

    def make_button(self, parent, text, command, primary=False, danger=False, width=None):
        bg = "#238636" if primary else "#21262d"
        hover = "#2ea043" if primary else "#30363d"
        if danger:
            bg, hover = "#da3633", "#f85149"
        button = tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            bg=bg,
            fg="#ffffff",
            activebackground=hover,
            activeforeground="#ffffff",
            bd=0,
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold" if primary else "normal"),
            padx=14,
            pady=9,
        )
        button.bind("<Enter>", lambda _event: button.configure(bg=hover))
        button.bind("<Leave>", lambda _event: button.configure(bg=bg))
        return button

    def build_row(self, parent, label, variable, command):
        tk.Label(
            parent,
            text=label,
            anchor="w",
            bg="#161b22",
            fg="#c9d1d9",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(fill="x", pady=(14, 6))
        row = tk.Frame(parent, bg="#161b22")
        row.pack(fill="x")
        tk.Entry(
            row,
            textvariable=variable,
            font=("Consolas", 10),
            bg="#0d1117",
            fg="#f0f6fc",
            insertbackground="#f0f6fc",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#30363d",
            highlightcolor="#58a6ff",
        ).pack(side="left", fill="x", expand=True, ipady=9)
        self.make_button(row, "浏览", command).pack(side="left", padx=(10, 0))

    def build(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Install.Horizontal.TProgressbar",
            troughcolor="#21262d",
            background="#2ea043",
            bordercolor="#21262d",
            lightcolor="#2ea043",
            darkcolor="#2ea043",
        )

        outer = tk.Frame(self.root, bg="#0d1117", padx=22, pady=22)
        outer.pack(fill="both", expand=True)

        shell = tk.Frame(outer, bg="#0d1117")
        shell.pack(fill="both", expand=True)

        hero = tk.Frame(shell, bg="#0d1117", width=280)
        hero.pack(side="left", fill="both", padx=(0, 18))
        hero.pack_propagate(False)

        logo = tk.Canvas(hero, width=64, height=64, bg="#0d1117", highlightthickness=0)
        logo.pack(anchor="w", pady=(8, 24))
        logo.create_oval(4, 4, 60, 60, fill="#238636", outline="#3fb950", width=2)
        logo.create_line(22, 34, 31, 43, 46, 22, fill="#ffffff", width=5, capstyle="round", joinstyle="round")

        tk.Label(
            hero,
            text=APP_TITLE,
            bg="#0d1117",
            fg="#f0f6fc",
            font=("Microsoft YaHei UI", 26, "bold"),
            justify="left",
            wraplength=250,
        ).pack(anchor="w")
        tk.Label(
            hero,
            text=f"{APP_VERSION}  安装向导",
            bg="#0d1117",
            fg="#8b949e",
            font=("Consolas", 11, "bold"),
        ).pack(anchor="w", pady=(12, 24))

        for item in ("本机部署", "桌面快捷方式", "局域网访问入口", "授权文件随包安装"):
            row = tk.Frame(hero, bg="#0d1117")
            row.pack(fill="x", pady=6)
            tk.Label(row, text="✓", bg="#0d1117", fg="#3fb950", font=("Microsoft YaHei UI", 12, "bold"), width=2).pack(side="left")
            tk.Label(row, text=item, bg="#0d1117", fg="#c9d1d9", font=("Microsoft YaHei UI", 10)).pack(side="left")

        tk.Label(
            hero,
            text="安装后自动启动服务，并创建可卸载记录。",
            bg="#0d1117",
            fg="#8b949e",
            font=("Microsoft YaHei UI", 9),
            wraplength=250,
            justify="left",
        ).pack(side="bottom", anchor="w")

        panel = tk.Frame(shell, bg="#161b22", padx=24, pady=22, highlightthickness=1, highlightbackground="#30363d")
        panel.pack(side="left", fill="both", expand=True)

        top = tk.Frame(panel, bg="#161b22")
        top.pack(fill="x")
        tk.Label(top, text="选择安装设置", bg="#161b22", fg="#f0f6fc", font=("Microsoft YaHei UI", 18, "bold")).pack(side="left", anchor="w")
        tk.Label(top, text="Windows 10+", bg="#21262d", fg="#58a6ff", font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=4).pack(side="right")

        tk.Label(
            panel,
            text="确认程序位置和资料目录，点击安装即可开始。",
            bg="#161b22",
            fg="#8b949e",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(8, 6))

        self.build_row(panel, "安装位置", self.install_path, self.browse_install)
        self.build_row(panel, "数据存储位置", self.data_path, self.browse_data)

        option = tk.Checkbutton(
            panel,
            text="开机自动启动本地服务入口",
            variable=self.autostart,
            bg="#161b22",
            fg="#c9d1d9",
            selectcolor="#0d1117",
            activebackground="#161b22",
            activeforeground="#f0f6fc",
            font=("Microsoft YaHei UI", 10),
        )
        option.pack(anchor="w", pady=(18, 10))

        self.progress = ttk.Progressbar(panel, style="Install.Horizontal.TProgressbar", mode="determinate", maximum=100, value=0)
        self.progress.pack(fill="x", pady=(12, 10))

        status_bar = tk.Frame(panel, bg="#161b22")
        status_bar.pack(fill="x", pady=(0, 18))
        tk.Label(status_bar, textvariable=self.status, bg="#161b22", fg="#58a6ff", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        tk.Label(status_bar, text="会写入当前用户注册表和卸载信息", bg="#161b22", fg="#8b949e", font=("Microsoft YaHei UI", 9)).pack(side="right")

        actions = tk.Frame(panel, bg="#161b22")
        actions.pack(fill="x", side="bottom")
        self.make_button(actions, "取消", self.root.destroy, width=10).pack(side="right", padx=(10, 0))
        self.make_button(actions, "安装并启动", self.install, primary=True, width=18).pack(side="right")

    def install(self):
        if not is_win10_or_newer():
            messagebox.showerror("系统不支持", "此安装包仅支持 Windows 10 及以上系统。")
            return

        target = Path(self.install_path.get()).expanduser()
        data_dir = Path(self.data_path.get()).expanduser()
        if not str(target).strip() or not str(data_dir).strip():
            messagebox.showerror("路径不能为空", "请填写安装位置和数据存储位置。")
            return

        try:
            stop_code = stop_installed_app_processes(target)
            if stop_code == 23:
                raise RuntimeError("端口 5088 正被其它程序占用。为避免误关程序，请先关闭占用程序后重试。")
            if stop_code == 24:
                raise RuntimeError("旧版本未能安全退出，请关闭工程影像管理平台后重试。")
            if stop_code != 0:
                raise RuntimeError("无法安全检查旧版本进程，安装已停止。")
            self.status.set("正在复制程序文件...")
            self.progress.configure(value=35)
            self.root.update_idletasks()
            copy_payload(target, data_dir)
            self.status.set("正在创建快捷方式和注册表...")
            self.progress.configure(value=72)
            self.root.update_idletasks()
            create_shortcut(target / DESKTOP_EXE_NAME, target / ICON_FILE_NAME, target)
            write_registry(target, data_dir, self.autostart.get())
        except Exception as exc:
            messagebox.showerror("安装失败", str(exc))
            self.status.set("安装失败")
            self.progress.configure(value=0)
            return

        self.status.set("安装完成")
        self.progress.configure(value=100)
        self.root.update_idletasks()
        messagebox.showinfo("安装完成", f"{APP_TITLE} {APP_VERSION} 安装完成，桌面快捷方式已创建。")
        start_app(target)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Installer().run()
