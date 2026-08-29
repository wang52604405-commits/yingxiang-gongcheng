import os
import json
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import winreg
import webbrowser
from pathlib import Path

import licensing
import tamper_guard
import tls_compat

try:
    import pystray
    from PIL import Image
    _HAS_TRAY = True
except Exception:  # pragma: no cover - 托盘不可用时退化为静默
    pystray = None
    Image = None
    _HAS_TRAY = False


APP_TITLE = "工程影像管理平台"
APP_VERSION = "A20260829-2.79"
UPDATE_URL = "https://api.shuiliyingxiang.cn/update/version.json"
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
        with tls_compat.secure_urlopen(UPDATE_URL, timeout=UPDATE_TIMEOUT) as resp:
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


def listener_pid(port=PORT):
    """Return the Windows PID listening on the application port, if any."""
    if os.name != "nt":
        return 0
    try:
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            text=True,
            encoding="mbcs",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    suffix = f":{int(port)}"
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[0].upper() == "TCP":
            if fields[1].endswith(suffix) and fields[3].upper() == "LISTENING":
                try:
                    return int(fields[4])
                except ValueError:
                    return 0
    return 0


def process_executable_path(pid):
    """读取进程完整可执行路径，用于在终止前校验它确属当前安装目录。"""
    if not pid or os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return None
            return Path(buffer.value).resolve()
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, ValueError):
        return None


def terminate_stale_server():
    """只停止当前安装目录里的旧 album_server；其它端口占用者绝不处理。"""
    pid = listener_pid()
    if not pid:
        return False
    executable = process_executable_path(pid)
    expected_dir = app_dir().resolve()
    if (
        executable is None
        or executable.name.lower() != SERVER_EXE_NAME.lower()
        or executable.parent.resolve() != expected_dir
    ):
        return False
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        return False
    for _ in range(20):
        if not is_port_open():
            return True
        time.sleep(0.15)
    return not is_port_open()


def local_server_version():
    """Read the version served on localhost without requiring login."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/bootstrap", timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data.get("app_version") or "")
    except Exception:
        return ""


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


def build_update_command(target, install_dir):
    """Build the unattended installer command for an in-place update.

    Inno Setup falls back to ``DefaultDirName`` when ``/DIR`` is omitted.
    That is unsafe for customers who selected a different install directory:
    the new package is then installed beside the old one and the existing
    shortcut keeps launching the old executable.
    """
    command = [
        str(Path(target).resolve()),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
    ]
    directory = Path(install_dir).expanduser()
    if directory.is_absolute():
        # 不能自己加引号：subprocess 传参时引号会被 Inno 当成路径的一部分，
        # 导致“文件夹名称不能包含下列任何字符”直接失败。
        # 含空格时由 subprocess 自动加外层引号即可。
        command.append(f"/DIR={directory.resolve()}")
    return command


def open_local_browser(url, port_open=True):
    """用系统浏览器以完整浏览器界面打开软件（有地址栏/标签页，同局域网直接访问）。"""
    exe = browser_exe()
    if exe:
        subprocess.Popen(
            [str(exe), "--new-window", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        webbrowser.open(url)


def ensure_server(data_dir):
    """启动（或复用）后台服务，保证 127.0.0.1:PORT 就绪。返回就绪状态。"""
    base = app_dir()
    if is_port_open():
        served_version = local_server_version()
        if served_version and _ver_tuple(served_version) >= _ver_tuple(APP_VERSION):
            return True
        # 端口被旧版本服务占用：杀掉重启
        if not terminate_stale_server():
            return False

    if getattr(sys, "frozen", False):
        ok, problems = tamper_guard.verify_installation(base)
        if not ok:
            return False

    server_exe = base / SERVER_EXE_NAME
    env = os.environ.copy()
    env["ALBUM_HOST"] = "0.0.0.0"
    env["ALBUM_PORT"] = str(PORT)
    env["ALBUM_DATA_DIR"] = str(data_dir)
    env["ALBUM_LICENSE_FILE"] = str(base / "license.dat")
    Path(env["ALBUM_DATA_DIR"]).mkdir(parents=True, exist_ok=True)

    try:
        if server_exe.exists():
            subprocess.Popen(
                [str(server_exe)],
                cwd=str(base),
                env=env,
                stdout=open(base / "server.out.log", "a", encoding="utf-8"),
                stderr=open(base / "server.err.log", "a", encoding="utf-8"),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            subprocess.Popen(
                [sys.executable, str(base / "server_launcher.py")],
                cwd=str(base),
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    except Exception:
        return False

    for _ in range(30):
        if is_port_open():
            return True
        time.sleep(0.2)
    return False


def download_update(url, new_ver, expected_sha256="", expected_size=0, install_dir="", on_progress=None):
    """旧兼容入口已停用；所有更新统一由本地页面的安全状态机处理。"""
    return False, "请打开软件页面完成更新"


class TrayApp:
    """轻量启动器：启动服务→校验版本→打开浏览器→托盘常驻。

    无本地界面，全部操作走系统浏览器与托盘菜单。
    """

    def __init__(self):
        self.base = app_dir()
        self.data_dir = read_reg_value(APP_REG_KEY, "DataDir", DEFAULT_DATA_DIR)
        self.local_url = f"http://127.0.0.1:{PORT}"
        self.tray = None
        self._icon_image = self._make_icon_image()

    def _make_icon_image(self):
        icon_path = self.base / ICON_FILE_NAME
        try:
            if icon_path.exists() and Image is not None:
                return Image.open(icon_path)
        except Exception:
            pass
        try:
            if Image is not None:
                img = Image.new("RGB", (64, 64), (15, 17, 23))
                return img
        except Exception:
            pass
        return None

    def notify(self, message, title=None):
        try:
            if self.tray is not None:
                self.tray.notify(message, title or APP_TITLE)
        except Exception:
            pass

    def open_app(self):
        if not ensure_server(self.data_dir):
            self.notify("服务启动失败，请检查网络或磁盘后重试")
            return
        open_local_browser(self.local_url)

    def check_update(self):
        # 托盘不再维护第二套下载/安装链路，避免重复下载以及旧逻辑按端口结束进程。
        # 页面会立即检查更新，并统一使用 app.py 的后台状态机与精确进程边界。
        if not is_port_open() and not ensure_server(self.data_dir):
            self.notify("服务启动失败，请稍后重试")
            return
        if not local_server_version():
            self.notify("本地端口被其它程序占用，无法打开更新页面")
            return
        open_local_browser(f"{self.local_url}/?check_update=1")
        self.notify("已打开更新页面")

    def setup_tray(self):
        if not _HAS_TRAY or pystray is None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("打开软件", lambda _icon, _item: threading.Thread(target=self.open_app, daemon=True).start()),
            pystray.MenuItem("检查更新", lambda _icon, _item: threading.Thread(target=self.check_update, daemon=True).start()),
            pystray.MenuItem("退出", lambda _icon, _item: self.quit()),
        )
        self.tray = pystray.Icon(APP_TITLE, icon=self._icon_image, title=APP_TITLE, menu=menu)

    def run_tray(self):
        if self.tray is None:
            self.run_forever_without_tray()
            return
        self.tray.run()

    def run_forever_without_tray(self):
        """托盘不可用时保持进程常驻，提供最基础服务保障。"""
        while True:
            time.sleep(3600)

    def quit(self):
        try:
            if self.tray is not None:
                self.tray.stop()
        except Exception:
            pass
        self._exit = True
        os._exit(0)

    def run(self):
        # 1) 启动后台服务
        if not ensure_server(self.data_dir):
            self.notify("服务启动失败，请稍后重试")
        # 2) 打开系统浏览器进入软件
        if is_port_open():
            open_local_browser(self.local_url)
        # 3) 托盘常驻
        self.setup_tray()
        self.run_tray()


def main() -> int:
    app = TrayApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
