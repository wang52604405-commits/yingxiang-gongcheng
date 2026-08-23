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

import licensing
import tamper_guard

try:
    import pystray
    from PIL import Image
    _HAS_TRAY = True
except Exception:  # pragma: no cover - 托盘不可用时退化为静默
    pystray = None
    Image = None
    _HAS_TRAY = False


APP_TITLE = "工程影像管理平台"
APP_VERSION = "A20260822-2.64"
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


def process_name(pid):
    """Read a process image name without depending on an extra package."""
    if not pid or os.name != "nt":
        return ""
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            text=True,
            encoding="mbcs",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).strip()
        if output and not output.startswith("INFO:"):
            return output.split(",", 1)[0].strip('"')
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def terminate_stale_server():
    """Stop an old copy of our server occupying the reserved port.

    5088 是应用专属端口，只要监听它的进程属于本应用（打包版 album_server.exe
    或开发版 python/pythonw 启动）就强制释放，避免更新时端口未停止导致覆盖失败。
    """
    pid = listener_pid()
    if not pid:
        return False
    name = process_name(pid).lower()
    # 只处理本应用的监听进程：打包版 album_server，源码版 python/pythonw
    allowed = {SERVER_EXE_NAME.lower(), "python.exe", "pythonw.exe"}
    if name not in allowed:
        return False
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
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
        "/CLOSEAPPLICATIONS",
    ]
    directory = Path(install_dir).expanduser()
    if directory.is_absolute():
        # 不能自己加引号：subprocess 传参时引号会被 Inno 当成路径的一部分，
        # 导致“文件夹名称不能包含下列任何字符”直接失败。
        # 含空格时由 subprocess 自动加外层引号即可。
        command.append(f"/DIR={directory.resolve()}")
    return command


def open_local_browser(url, port_open=True):
    """用系统浏览器打开软件界面（app 模式独立窗口，无地址栏）。"""
    exe = browser_exe()
    if exe:
        subprocess.Popen(
            [str(exe), f"--app={url}", "--new-window"],
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
    """后台下载并静默安装更新。返回 (ok, message)。

    支持断点续传（服务器需支持 Range）与进度回调；下载中断时保留临时文件供下次续传。
    """
    target = Path(tempfile.gettempdir()) / f"{APP_TITLE}-更新-{new_ver}.exe"
    digest = hashlib.sha256()
    try:
        # 已下载的字节与已有摘要（断点续传时累计）
        existing = target.stat().st_size if target.exists() else 0
        if existing:
            with open(target, "rb") as fh:
                for block in iter(lambda: fh.read(65536), b""):
                    digest.update(block)
            target_size = existing
        else:
            target_size = 0

        safe_url = urllib.parse.quote(url, safe=":/?&=%.@#")
        req = urllib.request.Request(safe_url)
        if target_size:
            req.add_header("Range", f"bytes={target_size}-")
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            # 206=部分内容(续传)，200=整包。续传时 total 是剩余字节
            if resp.status == 206:
                total = target_size + total
            elif resp.status == 200 and target_size:
                # 服务器不支持 Range，整包重写（丢弃已下部分）
                target.unlink(missing_ok=True)
                target_size = 0
                digest = hashlib.sha256()
                total = int(resp.headers.get("Content-Length") or 0)
            elif total == 0 and expected_size:
                total = expected_size
            mode = "ab" if (resp.status == 206 and target_size) else "wb"
            done = target_size
            with open(target, mode) as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
        size_done = target.stat().st_size if target.exists() else done
        if expected_size and size_done != expected_size:
            target.unlink(missing_ok=True)
            return False, "安装包大小校验失败，已取消"
        if expected_sha256 and digest.hexdigest().lower() != expected_sha256.lower():
            target.unlink(missing_ok=True)
            return False, "安装包完整性校验失败，已取消"
    except Exception as exc:
        # 中断时保留已下载的临时文件，供下次断点续传
        return False, f"下载失败：{friendly_error(exc)}"

    command = build_update_command(target, install_dir or app_dir())

    # 更新前先释放本应用占用的 5088 端口，避免安装程序覆盖文件时被旧服务阻塞。
    # CloseApplications 对无窗口 album_server.exe 不可靠，这里主动强杀监听者。
    terminate_stale_server()

    # 用独立进程启动安装器，让更新过程脱离本进程，安装完成由 Inno 静默接管重开。
    subprocess.Popen(command, cwd=str(Path(target).resolve().parent),
                     creationflags=subprocess.CREATE_NO_WINDOW)
    return True, "更新已开始，安装完成后软件自动生效"


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
        remote_ver, url, note, sha256, size = fetch_remote_version()
        if not remote_ver or _ver_tuple(remote_ver) <= _ver_tuple(APP_VERSION):
            self.notify("当前已是最新版本")
            return
        def _on_progress(done, total):
            try:
                if total:
                    cur = f"{done * 100 // total}%"
                else:
                    cur = f"{round(done / 1048576)} MB"
                self.notify(f"正在下载更新… {cur}", title=f"更新 {remote_ver}")
            except Exception:
                pass
        def fetch():
            ok, msg = download_update(url, remote_ver, sha256, size, self.base, on_progress=_on_progress)
            self.notify(msg)
        threading.Thread(target=fetch, daemon=True).start()
        self.notify(f"发现新版本 {remote_ver}，开始下载更新...")

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
