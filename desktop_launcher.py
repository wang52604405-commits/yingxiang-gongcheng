import os
import hashlib
import json
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import winreg
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import licensing
import tamper_guard


APP_TITLE = "工程影像管理平台"
APP_VERSION = "A20260809-2.47"
UPDATE_URL = "http://47.95.221.66/update/version.json"
UPDATE_TIMEOUT = 6
SERVER_EXE_NAME = "album_server.exe"
DESKTOP_EXE_NAME = "工程影像管理平台.exe"
PORT = 5088
ICON_FILE_NAME = "app_icon.ico"
APP_REG_KEY = r"Software\工程影像管理平台"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\工程影像管理平台"
DEFAULT_DATA_DIR = str(Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / APP_TITLE / "data")
COPYRIGHT_NOTICE = "版权声明：本软件仅限授权单位和授权机器使用，禁止复制传播、反编译、破解授权、绕过限制或二次销售。"


def friendly_error(exc):
    """把英文异常转成客户能看懂的中文提示。"""
    msg = str(exc)
    low = msg.lower()
    if "ascii" in low or "encode" in low:
        return "网络地址含特殊字符，下载失败"
    if "timed out" in low or "timeout" in low:
        return "连接服务器超时，请检查网络后重试"
    if "urlopen" in low or "http" in low or "ssl" in low or "certificate" in low:
        return "无法连接更新服务器，请检查网络后重试"
    if "refused" in low or "connection" in low or "connect" in low:
        return "无法连接服务器，请稍后重试"
    if "404" in low:
        return "更新文件不存在，请联系管理员"
    if "permission" in low or "denied" in low or "access" in low:
        return "没有权限访问，请以管理员身份运行"
    if "disk" in low or "space" in low:
        return "磁盘空间不足，请清理后重试"
    return msg or "未知错误"


def _ver_tuple(version):
    m = re.match(r"A(\d{8})-(\d+)\.(\d+)", version or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def fetch_remote_version():
    """获取服务器上的最新版本信息；兼容旧版 url/note 字段。"""
    try:
        with urllib.request.urlopen(UPDATE_URL, timeout=UPDATE_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (
            data.get("version"),
            data.get("download_url") or data.get("url"),
            data.get("note") or "\n".join(data.get("changelog") or []),
            str(data.get("sha256") or "").lower(),
            int(data.get("size") or 0),
        )
    except Exception:
        return None, None, "", "", 0


def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def is_port_open(host="127.0.0.1", port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def local_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def browser_exe():
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def read_reg_value(subkey, name, default=""):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            value, _value_type = winreg.QueryValueEx(key, name)
            return str(value or default)
    except OSError:
        return default


class DesktopLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_TITLE} {APP_VERSION}")
        self.root.geometry("780x500")
        self.root.resizable(False, False)
        self.root.configure(bg="#0d1117")
        self.base = app_dir()
        self.data_dir = read_reg_value(APP_REG_KEY, "DataDir", DEFAULT_DATA_DIR)
        self.server_process = None
        self.status = tk.StringVar(value="正在准备本机服务...")
        self.local_url = f"http://127.0.0.1:{PORT}"
        self.setup_url = f"{self.local_url}/setup"
        self.lan_url = tk.StringVar(value=f"http://{local_ip()}:{PORT}")
        self.machine_id = tk.StringVar(value=licensing.machine_id())

        icon_path = self.base / ICON_FILE_NAME
        if icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except tk.TclError:
                pass

        self.build_ui()
        self.root.after(120, self.start_server)
        self.check_update_async()

    def build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Launch.Horizontal.TProgressbar",
            troughcolor="#21262d",
            background="#2ea043",
            bordercolor="#21262d",
            lightcolor="#2ea043",
            darkcolor="#2ea043",
        )

        frame = tk.Frame(self.root, bg="#0d1117", padx=22, pady=22)
        frame.pack(fill="both", expand=True)

        header = tk.Frame(frame, bg="#0d1117")
        header.pack(fill="x", pady=(2, 18))

        mark = tk.Canvas(header, width=52, height=52, bg="#0d1117", highlightthickness=0)
        mark.pack(side="left", padx=(0, 14))
        mark.create_oval(4, 4, 48, 48, fill="#238636", outline="#3fb950", width=2)
        mark.create_line(18, 28, 25, 35, 38, 18, fill="#ffffff", width=4, capstyle="round", joinstyle="round")

        title_box = tk.Frame(header, bg="#0d1117")
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(title_box, text=APP_TITLE, bg="#0d1117", fg="#f0f6fc", font=("Microsoft YaHei UI", 24, "bold")).pack(anchor="w")
        tk.Label(
            title_box,
            text=f"{APP_VERSION}  本机服务入口",
            bg="#0d1117",
            fg="#8b949e",
            font=("Consolas", 10, "bold"),
        ).pack(anchor="w", pady=(4, 0))

        panel = tk.Frame(frame, bg="#161b22", padx=22, pady=20, highlightthickness=1, highlightbackground="#30363d")
        panel.pack(fill="both", expand=True)

        tk.Label(
            panel,
            text="服务地址",
            bg="#161b22",
            fg="#f0f6fc",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            panel,
            text="本机以桌面软件方式打开，同一局域网电脑可使用下方地址访问。",
            bg="#161b22",
            fg="#8b949e",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(6, 14))

        info = tk.Frame(panel, bg="#0d1117", padx=14, pady=12, highlightthickness=1, highlightbackground="#30363d")
        info.pack(fill="x")
        self.add_info_row(info, "本机地址", self.local_url)
        self.add_info_row(info, "局域网地址", self.lan_url.get())
        self.add_info_row(info, "机器 ID", self.machine_id.get())

        self.progress = ttk.Progressbar(panel, style="Launch.Horizontal.TProgressbar", mode="indeterminate")
        self.progress.pack(fill="x", pady=(16, 8))
        self.progress.start(12)
        tk.Label(panel, textvariable=self.status, bg="#161b22", fg="#58a6ff", wraplength=700, justify="left", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 14))

        actions = tk.Frame(panel, bg="#161b22")
        actions.pack(fill="x", pady=(4, 0))
        self.make_button(actions, "打开软件", lambda: self.open_app(), primary=True).pack(side="left", fill="x", expand=True)
        self.make_button(actions, "本机配置", lambda: self.open_app(self.setup_url)).pack(side="left", fill="x", expand=True, padx=(10, 0))
        self.make_button(actions, "账号与会员", lambda: self.open_app(f"{self.local_url}/license")).pack(side="left", fill="x", expand=True, padx=(10, 0))

        bottom = tk.Frame(panel, bg="#161b22")
        bottom.pack(fill="x", pady=(14, 0))
        self.make_button(bottom, "复制局域网地址", self.copy_lan_url).pack(side="left", fill="x", expand=True)
        self.make_button(bottom, "卸载软件", self.uninstall, danger=True).pack(side="left", fill="x", expand=True, padx=(10, 0))
        self.make_button(bottom, "关闭窗口", self.root.destroy).pack(side="left", fill="x", expand=True, padx=(10, 0))
        tk.Label(panel, text=COPYRIGHT_NOTICE, bg="#161b22", fg="#d29922", wraplength=700, justify="left", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(12, 0))

    def make_button(self, parent, text, command, primary=False, danger=False):
        bg = "#238636" if primary else "#21262d"
        hover = "#2ea043" if primary else "#30363d"
        if danger:
            bg, hover = "#da3633", "#f85149"
        button = tk.Button(
            parent,
            text=text,
            height=2,
            bg=bg,
            fg="#ffffff",
            activebackground=hover,
            activeforeground="#ffffff",
            bd=0,
            relief="flat",
            cursor="hand2",
            command=command,
            font=("Microsoft YaHei UI", 10, "bold" if primary else "normal"),
        )
        button.bind("<Enter>", lambda _event: button.configure(bg=hover))
        button.bind("<Leave>", lambda _event: button.configure(bg=bg))
        return button

    def add_info_row(self, parent, label, value):
        row = tk.Frame(parent, bg="#0d1117")
        row.pack(fill="x", pady=5)
        tk.Label(row, text=label, width=10, anchor="w", bg="#0d1117", fg="#8b949e", font=("Microsoft YaHei UI", 10)).pack(side="left")
        tk.Label(row, text=value, anchor="w", bg="#0d1117", fg="#f0f6fc", font=("Consolas", 10, "bold")).pack(side="left", fill="x", expand=True)

    def start_server(self):
        if is_port_open():
            self.status.set(f"服务已运行：{self.local_url}")
            self.progress.stop()
            self.progress.configure(mode="determinate", value=100, maximum=100)
            return

        if getattr(sys, "frozen", False):
            ok, problems = tamper_guard.verify_installation(self.base)
            if not ok:
                detail = "\n".join(problems)
                messagebox.showerror("程序完整性校验未通过", f"程序文件可能被修改，拒绝启动。\n\n{detail}")
                self.status.set("完整性校验未通过，拒绝启动。")
                self.progress.stop()
                return

        server_exe = self.base / SERVER_EXE_NAME
        env = os.environ.copy()
        env["ALBUM_HOST"] = "0.0.0.0"
        env["ALBUM_PORT"] = str(PORT)
        env["ALBUM_DATA_DIR"] = self.data_dir
        env["ALBUM_LICENSE_FILE"] = str(self.base / "license.dat")
        Path(env["ALBUM_DATA_DIR"]).mkdir(parents=True, exist_ok=True)

        try:
            if server_exe.exists():
                self.server_process = subprocess.Popen(
                    [str(server_exe)],
                    cwd=str(self.base),
                    env=env,
                    stdout=open(self.base / "server.out.log", "a", encoding="utf-8"),
                    stderr=open(self.base / "server.err.log", "a", encoding="utf-8"),
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                self.server_process = subprocess.Popen(
                    [sys.executable, str(self.base / "server_launcher.py")],
                    cwd=str(self.base),
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
        except Exception as exc:
            self.status.set(f"服务启动失败：{friendly_error(exc)}")
            return

        for _ in range(30):
            if is_port_open():
                self.status.set(f"服务已启动：{self.local_url}")
                self.progress.stop()
                self.progress.configure(mode="determinate", value=100, maximum=100)
                self.open_app()
                return
            time.sleep(0.2)
        self.status.set("服务启动中，请稍后点击“打开软件”。")

    def stop_server(self):
        try:
            if self.server_process and self.server_process.poll() is None:
                self.server_process.terminate()
                try:
                    self.server_process.wait(timeout=3)
                except Exception:
                    self.server_process.kill()
        except Exception:
            pass
        self.server_process = None

    def check_update_async(self):
        def worker():
            try:
                remote_ver, url, note, sha256, size = fetch_remote_version()
                if remote_ver and _ver_tuple(remote_ver) > _ver_tuple(APP_VERSION):
                    self.root.after(2000, lambda: self.prompt_update(remote_ver, url, note, sha256, size))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def prompt_update(self, remote_ver, url, note, sha256="", size=0):
        if not messagebox.askyesno(
            "发现新版本",
            f"发现新版本：{remote_ver}\n当前版本：{APP_VERSION}\n\n更新说明：{note or '无'}\n\n是否立即下载更新？",
        ):
            return
        self.download_update(url, remote_ver, sha256, size)

    def download_update(self, url, remote_ver, expected_sha256="", expected_size=0):
        target = Path(tempfile.gettempdir()) / f"{APP_TITLE}-更新-{remote_ver}.exe"
        win = tk.Toplevel(self.root)
        win.title("正在更新")
        win.geometry("380x130")
        win.resizable(False, False)
        win.configure(bg="#0d1117")
        tk.Label(win, text="正在下载更新，请稍候...", bg="#0d1117", fg="#f0f6fc",
                 font=("Microsoft YaHei UI", 11)).pack(pady=(20, 8))
        prog = ttk.Progressbar(win, length=320, mode="determinate", maximum=100)
        prog.pack(pady=4)
        pct_lbl = tk.Label(win, text="0%", bg="#0d1117", fg="#8b949e",
                           font=("Consolas", 9))
        pct_lbl.pack()
        self.status.set("正在下载更新...")

        def fetch():
            try:
                # 中文文件名需 percent-encode，否则 urllib 直接打开会报 ascii 编码错误
                safe_url = urllib.parse.quote(url, safe=":/?&=%.@#")
                with urllib.request.urlopen(safe_url, timeout=120) as resp, open(target, "wb") as f:
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    digest = hashlib.sha256()
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if total:
                            pct = int(done * 100 / total)
                            win.after(0, lambda p=pct: (prog.configure(value=p), pct_lbl.configure(text=f"{p}%")))
                if expected_size and done != expected_size:
                    raise ValueError(f"安装包大小校验失败（应为 {expected_size}，实际 {done}）")
                if expected_sha256 and digest.hexdigest().lower() != expected_sha256.lower():
                    raise ValueError("安装包完整性校验失败，请勿运行该文件")
            except Exception as exc:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                win.after(0, lambda: (win.destroy(), messagebox.showerror("更新失败", f"下载失败：{friendly_error(exc)}")))
                return
            win.after(0, lambda: (win.destroy(), self.finish_update(target)))

        threading.Thread(target=fetch, daemon=True).start()

    def finish_update(self, target):
        try:
            self.stop_server()
        except Exception:
            pass
        self.root.destroy()
        subprocess.Popen(
            [str(target), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            cwd=str(target.parent),
        )

    def open_app(self, url=None):
        """以原生窗口打开软件界面（WebView2），不再依赖浏览器窗口。

        局域网其他电脑仍可通过浏览器访问，不受影响。
        """
        if not is_port_open():
            self.start_server()
            return
        url = url or self.local_url
        icon_path = self.base / ICON_FILE_NAME
        try:
            import webview
            # 允许桌面窗口内下载文件（CSV/Excel/ZIP 等），默认是禁用的，点了会没反应
            webview.settings['ALLOW_DOWNLOADS'] = True

            self.root.withdraw()
            window = webview.create_window(
                APP_TITLE, url, width=1440, height=900, min_size=(1024, 700)
            )
            try:
                if icon_path.exists():
                    window.set_icon(str(icon_path))
            except Exception:
                pass
            webview.start()
            self.root.deiconify()
        except Exception:
            # 本机没有 WebView2 运行时等异常情况时，退回浏览器打开
            self.root.deiconify()
            self.open_url(url)

    def open_url(self, url):
        if not is_port_open():
            self.start_server()
            return
        exe = browser_exe()
        if exe:
            subprocess.Popen([str(exe), f"--app={url}", "--new-window"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(url)

    def copy_lan_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.lan_url.get())
        self.status.set("局域网地址已复制。")

    def uninstall(self):
        remove_data = messagebox.askyesnocancel(
            "确认卸载",
            "卸载会删除程序文件、桌面快捷方式、开机启动和注册表信息。\n\n是否同时删除数据目录？\n\n选择“是”：删除数据目录\n选择“否”：保留数据目录\n选择“取消”：不卸载",
        )
        if remove_data is None:
            return
        install_dir = self.base
        data_dir = Path(self.data_dir)
        desktop_paths = [Path.home() / "Desktop", Path.home() / "桌面"]
        shortcuts = [path / f"{APP_TITLE}.lnk" for path in desktop_paths]
        shortcut_lines = "\n".join(f"Remove-Item -LiteralPath '{self.ps_quote(path)}' -Force -ErrorAction SilentlyContinue" for path in shortcuts)
        remove_data_line = f"Remove-Item -LiteralPath '{self.ps_quote(data_dir)}' -Recurse -Force -ErrorAction SilentlyContinue" if remove_data else ""
        ps_script = f"""
$ErrorActionPreference = "SilentlyContinue"
Start-Sleep -Seconds 1
$ServerExe = '{self.ps_quote(install_dir / SERVER_EXE_NAME)}'
$DesktopExe = '{self.ps_quote(install_dir / DESKTOP_EXE_NAME)}'
Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -eq $ServerExe -or $_.ExecutablePath -eq $DesktopExe }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}
{shortcut_lines}
Remove-ItemProperty -Path 'HKCU:\\{RUN_KEY}' -Name '{APP_TITLE}' -Force -ErrorAction SilentlyContinue
Remove-Item -Path 'HKCU:\\{UNINSTALL_KEY}' -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path 'HKCU:\\{APP_REG_KEY}' -Recurse -Force -ErrorAction SilentlyContinue
netsh advfirewall firewall delete rule name="{APP_TITLE} {PORT}" | Out-Null
{remove_data_line}
Remove-Item -LiteralPath '{self.ps_quote(install_dir)}' -Recurse -Force
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force
"""
        temp_script = Path(tempfile.gettempdir()) / "uninstall_project_album.ps1"
        temp_script.write_text(ps_script, encoding="utf-8")
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(temp_script)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.root.destroy()

    @staticmethod
    def ps_quote(path):
        return str(path).replace("'", "''")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    DesktopLauncher().run()
