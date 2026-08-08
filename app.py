import csv
import hashlib
import io
import json
import os
import re
import shutil
import socket
import sys
import threading
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_file, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import licensing
import cloud_client
import tamper_guard
import watermark_ocr

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - handled at runtime with a clear message
    load_workbook = None


BASE_DIR = Path(__file__).resolve().parent
APP_DISPLAY_NAME = "工程影像管理平台"
SETUP_CONFIG_PATH = BASE_DIR / "album_config.json"
PORTABLE_DATA_DIR = BASE_DIR / "data"
DATA_DIR = Path(os.environ.get("ALBUM_DATA_DIR", r"D:\工程影像资料")).expanduser()
ALBUMS_DIR = DATA_DIR / "albums"
USERS_PATH = DATA_DIR / "users.json"
OTHER_IMAGES_PATH = DATA_DIR / "other_images.json"
PROJECT_INFO_PATH = DATA_DIR / "project_info.json"
ENGINEERING_PROJECTS_PATH = DATA_DIR / "engineering_projects.json"
SHARE_POINTS_PATH = DATA_DIR / "share_points.json"
NUMBERING_RULES_PATH = DATA_DIR / "numbering_rules.json"
ENGINEERING_SETTINGS_PATH = DATA_DIR / "engineering_settings.json"
OTHER_IMAGES_TEMPLATE_DIR = Path(os.environ.get("ALBUM_OTHER_IMAGES_TEMPLATE_DIR", r"E:\龙泉缓洪工程施工照片")).expanduser()
LEGACY_ALBUMS_DIR = BASE_DIR / "albums"
LEGACY_USERS_PATH = BASE_DIR / "users.json"
DELETE_SAFETY_PASSWORD = os.environ.get("ALBUM_DELETE_PASSWORD", "114405")
DEFAULT_ENGINEERING_PROJECT_ID = "default"
OTHER_IMAGE_MARKER = "_other_image"
SHARE_POINTS_PER_PERSON = 5
SHARE_POINTS_REDEEM_THRESHOLD = 30
SHARE_POINTS_DAILY_LIMIT = 6
LIFETIME_LICENSE_PRICE = 129
DEFAULT_PROJECT_TABLE = Path("")
PROJECT_TEMPLATE_XLSX_PATH = BASE_DIR / "assets" / "project_template.xlsx"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
PHOTO_CATEGORIES = {"construction", "supervision"}
PHOTO_CATEGORY_LABELS = {
    "construction": "施工单元影像",
    "supervision": "监理单元影像",
}
PHOTO_ORIENTATIONS = {"landscape", "portrait"}
PHOTO_ORIENTATION_LABELS = {
    "landscape": "横版",
    "portrait": "竖版",
}


def normalize_photo_rotation(value):
    try:
        rotation = int(value or 0)
    except (TypeError, ValueError):
        rotation = 0
    return rotation if rotation in {0, 90, 180, 270} else 0


def normalize_print_photo_size(value):
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if size <= 0:
        return 0
    return round(max(1, min(30, size)), 2)


def detect_photo_orientation(path):
    """不借助 AI，直接读图片像素判断方向：按 EXIF 摆正后，高>宽为竖版，否则横版。"""
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size
        return "portrait" if height > width else "landscape"
    except Exception:
        return ""


def photo_exif_date(path):
    """从照片 EXIF 读拍摄时间，返回 YYYY-MM-DD 或空串。"""
    try:
        from PIL import Image

        with Image.open(path) as img:
            exif = img.getexif()
            raw = exif.get(0x9003) or exif.get(0x0132) or ""
        m = re.search(r"(20\d{2})[:\-/](\d{1,2})[:\-/](\d{1,2})", str(raw))
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    except Exception:
        pass
    return ""


DEFAULT_NUMBERING_RULES = {
    "construction": {
        "template": "{code}-SY{seq}",
        "unit_template": "{unit_code}-SY{seq}",
        "process_template": "{unit_code}-{process_code}-SY{seq}",
        "start": 1,
        "digits": 3,
        "label": "施工单元影像",
    },
    "supervision": {
        "template": "{code}-JY{seq}",
        "unit_template": "{unit_code}-JY{seq}",
        "process_template": "{unit_code}-{process_code}-JY{seq}",
        "start": 1,
        "digits": 3,
        "label": "监理单元影像",
    },
}
DEFAULT_ENGINEERING_SETTINGS = {
    "numbering_mode": "custom",
    "process_prefix": "",
    "process_digits": 3,
    "unit_order_digits": 3,
    "print_layout": "landscape",
    "print_page_size": 4,
    "print_photo_width_cm": 0,
    "print_photo_height_cm": 0,
    "print_caption_font_size": 7.2,
    "print_caption_position": "left",
    "watermark_ocr_enabled": False,
    "photo_detail_fields": [
        {"label": "编号", "source": "id", "value": ""},
        {"label": "题名", "source": "title", "value": ""},
        {"label": "施工部位", "source": "project_name", "value": ""},
        {"label": "桩号", "source": "custom", "value": ""},
        {"label": "简要描述", "source": "description", "value": ""},
        {"label": "摄影者", "source": "photographer", "value": ""},
        {"label": "拍摄时间", "source": "photo_date", "value": ""},
    ],
    "numbering_rules": DEFAULT_NUMBERING_RULES,
}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
PROJECT_IMPORT_EXTENSIONS = EXCEL_EXTENSIONS | {".csv"}
PROJECT_TEMPLATE_HEADERS = [
    "合同工程名称",
    "单位工程名称",
    "单位工程编码",
    "分部工程名称",
    "分部工程编码",
    "单元工程名称",
    "单元工程编码",
    "关键词",
]
PROJECT_TEMPLATE_ROWS = [
    ["示例工程", "单位工程一", "GC-001", "分部工程一", "GC-001-01", "单元工程一", "GC-001-01-001", ""],
    ["示例工程", "单位工程一", "GC-001", "分部工程一", "GC-001-01", "单元工程二", "GC-001-01-002", ""],
    ["示例工程", "单位工程二", "GC-002", "分部工程一", "GC-002-01", "单元工程三", "GC-002-01-001", ""],
]


def default_standard_unit_rules():
    process = "process"
    unit = "unit"
    return [
        {"keywords": ["水泥土搅拌桩防渗墙"], "standard_unit_name": "水泥土搅拌防渗墙单元工程", "division_type": unit, "processes": []},
        {"keywords": ["水泥土搅拌桩"], "standard_unit_name": "水泥土搅拌桩法复合地基处理单元工程", "division_type": process, "processes": ["水泥土搅拌桩", "褥垫层"]},
        {"keywords": ["混凝土防渗墙", "防渗墙"], "standard_unit_name": "混凝土防渗墙单元工程", "division_type": process, "processes": ["混凝土防渗墙造孔", "混凝土防渗墙清孔", "混凝土防渗墙钢筋笼制作与安装", "混凝土浇筑"]},
        {"keywords": ["灌注桩"], "standard_unit_name": "钻孔灌注桩单元工程", "division_type": process, "processes": ["钻孔灌注桩钻孔", "钢筋笼制作与安装", "混凝土浇筑"]},
        {"keywords": ["预制桩"], "standard_unit_name": "钢筋混凝土预制桩单元工程", "division_type": unit, "processes": []},
        {"keywords": ["岸坡开挖"], "standard_unit_name": "土质岸坡开挖单元工程", "division_type": unit, "processes": []},
        {"keywords": ["土方开挖", "基坑开挖", "开挖"], "standard_unit_name": "土质地基开挖单元工程", "division_type": unit, "processes": []},
        {"keywords": ["石方开挖", "岩石开挖"], "standard_unit_name": "岩石地基开挖单元工程", "division_type": unit, "processes": []},
        {"keywords": ["堤基清理", "基础清理"], "standard_unit_name": "陆地基础清理和处理单元工程", "division_type": unit, "processes": []},
        {"keywords": ["堤身填筑", "土方填筑", "土料填筑", "土方回填", "回填"], "standard_unit_name": "土料填筑单元工程", "division_type": unit, "processes": []},
        {"keywords": ["土料吹填", "吹填"], "standard_unit_name": "土料吹填单元工程", "division_type": process, "processes": ["围堰修筑", "土料吹填"]},
        {"keywords": ["碎石垫层", "砂垫层", "粗砂碎石垫层", "砂砾垫层", "卵石垫层"], "standard_unit_name": "碎石或卵石与砂垫层单元工程", "division_type": unit, "processes": []},
        {"keywords": ["土工膜"], "standard_unit_name": "土工膜防渗单元工程", "division_type": process, "processes": ["下垫层", "土工膜铺设与回填"]},
        {"keywords": ["土工布", "土工织物铺设"], "standard_unit_name": "土工织物铺设单元工程", "division_type": unit, "processes": []},
        {"keywords": ["格宾石笼", "格网石笼"], "standard_unit_name": "格网石笼生态防护单元工程", "division_type": unit, "processes": []},
        {"keywords": ["石笼护坡"], "standard_unit_name": "石笼护坡单元工程", "division_type": unit, "processes": []},
        {"keywords": ["干砌石护坡", "干砌石"], "standard_unit_name": "干砌石护坡单元工程", "division_type": unit, "processes": []},
        {"keywords": ["浆砌石护坡", "浆砌石", "浆砌预制块"], "standard_unit_name": "浆砌石或浆砌预制块护坡单元工程", "division_type": unit, "processes": []},
        {"keywords": ["护脚", "防冲体抛投", "抛石"], "standard_unit_name": "护脚工程单元工程", "division_type": process, "processes": ["散抛石防冲体制备", "石笼防冲体制备", "预制块防冲体制备", "土工袋或土工包防冲体制备", "柴枕防冲体制备", "防冲体抛投"]},
        {"keywords": ["排水沟"], "standard_unit_name": "现浇混凝土排水沟单元工程", "division_type": unit, "processes": []},
        {"keywords": ["止水"], "standard_unit_name": "面板表面止水单元工程", "division_type": unit, "processes": []},
        {"keywords": ["预制构件安装", "T梁安装"], "standard_unit_name": "混凝土预制构件安装单元工程", "division_type": unit, "processes": []},
        {"keywords": ["普通混凝土", "钢筋混凝土", "混凝土垫层", "混凝土护底", "混凝土底板", "混凝土墙身", "混凝土中墩", "混凝土边墩", "混凝土缝墩", "混凝土检修板", "混凝土铺装", "混凝土"], "standard_unit_name": "普通混凝土单元工程", "division_type": process, "processes": ["普通混凝土备仓", "普通混凝土浇筑"]},
        {"keywords": ["植草"], "standard_unit_name": "植草防护单元工程", "division_type": unit, "processes": []},
        {"keywords": ["植树"], "standard_unit_name": "植树防护单元工程", "division_type": unit, "processes": []},
    ]


def standard_rules_from_checklist():
    path = BASE_DIR / "水利单元工程划分清单.csv"
    if not path.exists():
        return []
    rules = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                name = str(row.get("单元名称") or "").strip()
                if not name:
                    continue
                processes = [p.strip() for p in str(row.get("工序名称") or "").split("、") if p.strip()]
                division = "process" if "划分工序" in str(row.get("备注") or "") and not str(row.get("备注") or "").startswith("不") else "unit"
                rules.append({"keywords": [name.replace("单元工程", "")], "standard_unit_name": name, "division_type": division, "processes": processes})
    except Exception:
        return []
    return rules


def standard_unit_rules():
    return default_standard_unit_rules() + standard_rules_from_checklist()


def match_standard_unit(unit_name):
    text = normalize_match_text(unit_name)
    for rule in standard_unit_rules():
        for keyword in rule.get("keywords", []):
            keyword_text = normalize_match_text(keyword)
            if keyword and (keyword in str(unit_name or "") or keyword in text or (keyword_text and keyword_text in text)):
                return {
                    "standard_unit_name": rule.get("standard_unit_name", ""),
                    "division_type": rule.get("division_type") or "unit",
                    "processes": list(rule.get("processes") or []),
                    "match_keyword": keyword,
                }
    return {"standard_unit_name": "", "division_type": "unit", "processes": [], "match_keyword": ""}

def _load_or_create_secret_key():
    """session 签名密钥：优先环境变量，否则随机生成并持久化到数据目录。

    公开已知的默认密钥会让局域网任意设备都能伪造 session cookie，
    这里必须用不可预测且跨重启稳定的随机值。
    """
    env_key = os.environ.get("ALBUM_SECRET_KEY")
    if env_key and len(env_key) >= 16:
        return env_key
    key_path = DATA_DIR / ".session_secret"
    try:
        if key_path.exists():
            secret = key_path.read_text(encoding="ascii").strip()
            if len(secret) >= 16:
                return secret
    except OSError:
        pass
    secret = os.urandom(32).hex()
    try:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(secret, encoding="ascii")
    except OSError:
        pass
    return secret


app = Flask(__name__)
app.secret_key = _load_or_create_secret_key()
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024
DATA_DIR.mkdir(parents=True, exist_ok=True)
ALBUMS_DIR.mkdir(parents=True, exist_ok=True)


@app.before_request
def _public_gate():
    """公网访问限制：非局域网 IP 只能走云预览受限通道，其余功能完全限制。"""
    if is_lan_request():
        return None
    path = request.path
    # 静态资源与云预览相关放行
    if path.startswith("/assets/") or path.startswith("/api/cloud/"):
        return None
    if path in {"/", "/license"}:
        return render_template("restricted.html"), 403
    # 其余一律受限
    if path.startswith("/api/"):
        return jsonify({"ok": False, "error": "公网访问受限：请在局域网内使用完整功能，或使用云预览查看"}), 403
    return render_template("restricted.html"), 403


def migrate_legacy_storage():
    if LEGACY_ALBUMS_DIR.exists() and not any(ALBUMS_DIR.iterdir()):
        shutil.copytree(LEGACY_ALBUMS_DIR, ALBUMS_DIR, dirs_exist_ok=True)
    if LEGACY_USERS_PATH.exists() and not USERS_PATH.exists():
        shutil.copy2(LEGACY_USERS_PATH, USERS_PATH)


migrate_legacy_storage()


def get_lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def runtime_host():
    return os.environ.get("ALBUM_HOST", "0.0.0.0")


def runtime_port():
    try:
        return int(os.environ.get("ALBUM_PORT", "5088"))
    except ValueError:
        return 5088


def is_local_setup_request():
    remote = (request.remote_addr or "").strip().lower()
    return remote in {"127.0.0.1", "::1", "localhost"} or remote.startswith("127.")


def is_lan_request():
    """是否局域网请求。公网（非局域网 IP）返回 False，用于公网访问受限。"""
    remote = (request.remote_addr or "").strip().lower()
    if remote in {"127.0.0.1", "::1", "localhost"} or remote.startswith("127."):
        return True
    # 常见私网段
    if remote.startswith("10.") or remote.startswith("192.168."):
        return True
    if remote.startswith("172."):
        try:
            second = int(remote.split(".")[1])
            if 16 <= second <= 31:
                return True
        except (ValueError, IndexError):
            pass
    return False


# 公网请求允许访问的路径（云预览受限入口）；其余功能完全限制
PUBLIC_ALLOWED_PREFIXES = (
    "/api/cloud/preview",
    "/api/cloud/preview-login",
    "/api/cloud/login",
    "/api/cloud/register",
    "/api/cloud/logout",
    "/api/cloud/status",
)


def public_restricted():
    """公网请求：非局域网 IP 访问完整功能时，强制走云预览受限通道。

    返回 True 表示已拦截（渲染受限提示），False 表示放行。
    """
    if is_lan_request():
        return False
    path = request.path
    # 静态资源、云预览相关放行
    if path.startswith("/assets/") or path.startswith("/api/cloud/"):
        return False
    if path in {"/", "/license"} or path.startswith("/api/cloud"):
        return False
    # 其余 API 与页面：公网一律受限
    return True


def write_text_file(path: Path, content: str):
    # .ps1 必须带 BOM，否则 Windows PowerShell 5.1 按 ANSI/GBK 解析中文会乱码；
    # .bat 保持无 BOM，避免 cmd 把首行 BOM 当成命令。
    encoding = "utf-8-sig" if str(path).lower().endswith(".ps1") else "utf-8"
    with path.open("w", encoding=encoding, newline="\r\n") as f:
        f.write(content.strip() + "\n")


def portable_start_bat(port: int):
    return f"""
@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "ALBUM_HOST=0.0.0.0"
set "ALBUM_PORT={port}"
set "ALBUM_DATA_DIR=D:\工程影像资料"

if not exist "%ALBUM_DATA_DIR%" mkdir "%ALBUM_DATA_DIR%"

where python >nul 2>nul
if errorlevel 1 (
  echo 未检测到 Python。请先安装 Python 3.9 或更高版本，并勾选 Add python.exe to PATH。
  echo 下载地址：https://www.python.org/downloads/
  pause
  exit /b 1
)

python -c "import flask, openpyxl" >nul 2>nul
if errorlevel 1 (
  echo 正在安装运行依赖，请稍等...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 依赖安装失败。请检查网络后重新运行本文件。
    pause
    exit /b 1
  )
)

start "" powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:%ALBUM_PORT%/setup'"

echo.
echo 工程影像管理平台已启动。
echo 本机配置页：http://127.0.0.1:%ALBUM_PORT%/setup
echo 局域网登录网址会在下方显示。其他电脑需连接同一个局域网。
echo 若其他电脑无法打开，请在 Windows 防火墙中允许 TCP %ALBUM_PORT% 端口。
echo.
python run.py
pause
"""


def portable_autostart_ps1(port: int):
    return f"""
$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = {port}
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {{
    exit 1
}}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {{
    exit 0
}}

$env:ALBUM_HOST = "0.0.0.0"
$env:ALBUM_PORT = "$Port"
$env:ALBUM_DATA_DIR = "D:\工程影像资料"
New-Item -ItemType Directory -Path $env:ALBUM_DATA_DIR -Force | Out-Null

Start-Process `
    -FilePath $Python.Source `
    -ArgumentList "run.py" `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$ProjectDir\\server.out.log" `
    -RedirectStandardError "$ProjectDir\\server.err.log"
"""


def setup_status():
    port = runtime_port()
    lan_ip = get_lan_ip()
    local_url = f"http://127.0.0.1:{port}"
    lan_url = f"http://{lan_ip}:{port}"
    config = {}
    if SETUP_CONFIG_PATH.exists():
        try:
            config = json.loads(SETUP_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {}
    return {
        "host": runtime_host(),
        "port": port,
        "lan_ip": lan_ip,
        "local_url": local_url,
        "setup_url": f"{local_url}/setup",
        "lan_url": lan_url,
        "lan_setup_url": f"{lan_url}/setup",
        "data_dir": str(DATA_DIR),
        "portable_data_dir": str(PORTABLE_DATA_DIR),
        "app_dir": str(BASE_DIR),
        "python_exe": sys.executable,
        "start_script": str(BASE_DIR / "start_album.bat"),
        "config_path": str(SETUP_CONFIG_PATH),
        "firewall_command": (
            f'netsh advfirewall firewall add rule name="{APP_DISPLAY_NAME} {port}" '
            f"dir=in action=allow protocol=TCP localport={port}"
        ),
        "is_lan_bound": runtime_host() in {"0.0.0.0", "::"},
        "can_auto_config": is_local_setup_request(),
        "configured_at": config.get("configured_at", ""),
    }


def write_portable_setup(port: int):
    PORTABLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    portable_albums = PORTABLE_DATA_DIR / "albums"
    portable_albums.mkdir(parents=True, exist_ok=True)
    if LEGACY_ALBUMS_DIR.exists() and not any(portable_albums.iterdir()):
        shutil.copytree(LEGACY_ALBUMS_DIR, portable_albums, dirs_exist_ok=True)
    portable_users = PORTABLE_DATA_DIR / "users.json"
    if LEGACY_USERS_PATH.exists() and not portable_users.exists():
        shutil.copy2(LEGACY_USERS_PATH, portable_users)
    write_text_file(BASE_DIR / "start_album.bat", portable_start_bat(port))
    write_text_file(BASE_DIR / "autostart_album.ps1", portable_autostart_ps1(port))
    payload = {
        "configured_at": now_text(),
        "host": "0.0.0.0",
        "port": port,
        "portable_data_dir": str(PORTABLE_DATA_DIR),
        "start_script": str(BASE_DIR / "start_album.bat"),
    }
    SETUP_CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run_lan_server():
    host = runtime_host()
    port = runtime_port()
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    if getattr(sys, "frozen", False):
        ok, problems = tamper_guard.verify_installation()
        if not ok:
            print("程序完整性校验未通过，拒绝启动：")
            for message in problems:
                print(" -", message)
            sys.exit(1)
    lan_ip = get_lan_ip()
    print(f"Local: http://127.0.0.1:{port}")
    print(f"LAN:   http://{lan_ip}:{port}")
    print("Keep this window open while other computers use the system.")
    # 启动后稍候同步一次云预览（缩略图+编号），不阻塞主服务
    threading.Timer(3.0, sync_cloud_preview_async).start()
    app.run(host=host, port=port, debug=debug, threaded=True)


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def json_error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    if isinstance(exc, HTTPException):
        return json_error(exc.description or "请求错误", exc.code or 500)
    traceback.print_exc()
    # 不把内部异常消息/堆栈路径返回给客户端，避免信息泄露
    return json_error("服务器内部错误，请稍后重试。详情已记录到日志。", 500)


def read_text_with_fallback(path):
    raw = Path(path).read_bytes()
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"文件编码无法识别，请另存为 UTF-8 或 Excel xlsx 后再导入：{last_error}")


def deep_default_settings():
    return json.loads(json.dumps(DEFAULT_ENGINEERING_SETTINGS, ensure_ascii=False))


def read_engineering_settings():
    settings = deep_default_settings()
    if ENGINEERING_SETTINGS_PATH.exists():
        try:
            saved = json.loads(read_text_with_fallback(ENGINEERING_SETTINGS_PATH))
        except (OSError, ValueError, json.JSONDecodeError):
            saved = {}
        if isinstance(saved, dict):
            settings.update({k: v for k, v in saved.items() if k != "numbering_rules"})
            saved_rules = saved.get("numbering_rules")
            if isinstance(saved_rules, dict):
                for category in PHOTO_CATEGORIES:
                    if isinstance(saved_rules.get(category), dict):
                        settings["numbering_rules"][category].update(saved_rules[category])
    legacy_rules = read_numbering_rules_file()
    for category in PHOTO_CATEGORIES:
        settings["numbering_rules"][category].update(legacy_rules.get(category, {}))
    settings["numbering_mode"] = settings.get("numbering_mode") if settings.get("numbering_mode") in {"custom", "unit_order"} else "custom"
    try:
        settings["process_digits"] = max(1, min(8, int(settings.get("process_digits", 3))))
    except (TypeError, ValueError):
        settings["process_digits"] = 3
    try:
        settings["unit_order_digits"] = max(1, min(8, int(settings.get("unit_order_digits", 3))))
    except (TypeError, ValueError):
        settings["unit_order_digits"] = 3
    try:
        settings["print_page_size"] = int(settings.get("print_page_size", 4))
    except (TypeError, ValueError):
        settings["print_page_size"] = 4
    if settings["print_page_size"] not in {1, 2, 4}:
        settings["print_page_size"] = 4
    settings["print_layout"] = "portrait" if settings.get("print_layout") == "portrait" else "landscape"
    settings["print_photo_width_cm"] = normalize_print_photo_size(settings.get("print_photo_width_cm", 0))
    settings["print_photo_height_cm"] = normalize_print_photo_size(settings.get("print_photo_height_cm", 0))
    try:
        settings["print_caption_font_size"] = max(5, min(14, float(settings.get("print_caption_font_size", 7.2))))
    except (TypeError, ValueError):
        settings["print_caption_font_size"] = 7.2
    settings["print_caption_position"] = settings.get("print_caption_position") if settings.get("print_caption_position") in {"left", "right", "top", "bottom"} else "left"
    fields = settings.get("photo_detail_fields")
    if not isinstance(fields, list) or not fields:
        settings["photo_detail_fields"] = deep_default_settings()["photo_detail_fields"]
    return settings


def write_engineering_settings(payload):
    current = read_engineering_settings()
    payload = payload or {}
    current["numbering_mode"] = payload.get("numbering_mode") if payload.get("numbering_mode") in {"custom", "unit_order"} else current["numbering_mode"]
    current["process_prefix"] = str(payload.get("process_prefix", current.get("process_prefix", ""))).strip()
    for field, default_value in [("process_digits", 3), ("unit_order_digits", 3)]:
        try:
            current[field] = max(1, min(8, int(payload.get(field, current.get(field, default_value)))))
        except (TypeError, ValueError):
            raise ValueError(f"{field} 必须是数字")
    current["print_layout"] = "portrait" if payload.get("print_layout", current["print_layout"]) == "portrait" else "landscape"
    try:
        page_size = int(payload.get("print_page_size", current.get("print_page_size", 4)))
    except (TypeError, ValueError) as exc:
        raise ValueError("每页张数必须是数字") from exc
    if page_size not in {1, 2, 4}:
        raise ValueError("每页张数只能选择 1、2、4")
    current["print_page_size"] = page_size
    current["print_photo_width_cm"] = normalize_print_photo_size(payload.get("print_photo_width_cm", current.get("print_photo_width_cm", 0)))
    current["print_photo_height_cm"] = normalize_print_photo_size(payload.get("print_photo_height_cm", current.get("print_photo_height_cm", 0)))
    try:
        current["print_caption_font_size"] = max(5, min(14, float(payload.get("print_caption_font_size", current.get("print_caption_font_size", 7.2)))))
    except (TypeError, ValueError) as exc:
        raise ValueError("照片说明字号必须是数字") from exc
    current["print_caption_position"] = payload.get("print_caption_position") if payload.get("print_caption_position") in {"left", "right", "top", "bottom"} else current.get("print_caption_position", "left")
    current["watermark_ocr_enabled"] = bool(payload.get("watermark_ocr_enabled", current.get("watermark_ocr_enabled", True)))
    if isinstance(payload.get("photo_detail_fields"), list):
        fields = []
        for item in payload.get("photo_detail_fields"):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            if not label:
                continue
            fields.append({
                "label": label[:30],
                "source": str(item.get("source") or "custom").strip()[:40],
                "value": str(item.get("value") or "").strip()[:200],
            })
        if fields:
            current["photo_detail_fields"] = fields
    if isinstance(payload.get("numbering_rules"), dict):
        current["numbering_rules"] = write_numbering_rules(payload.get("numbering_rules"), persist=False)
    ENGINEERING_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENGINEERING_SETTINGS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def read_numbering_rules_file():
    rules = json.loads(json.dumps(DEFAULT_NUMBERING_RULES, ensure_ascii=False))
    if not NUMBERING_RULES_PATH.exists():
        return rules
    try:
        saved = json.loads(read_text_with_fallback(NUMBERING_RULES_PATH))
    except (OSError, ValueError, json.JSONDecodeError):
        return rules
    if not isinstance(saved, dict):
        return rules
    for category in PHOTO_CATEGORIES:
        item = saved.get(category) or {}
        if not isinstance(item, dict):
            continue
        for key in ("template", "unit_template", "process_template"):
            value = str(item.get(key) or "").strip()
            if value:
                rules[category][key] = value
        try:
            rules[category]["start"] = max(1, int(item.get("start", rules[category]["start"])))
        except (TypeError, ValueError):
            pass
        try:
            rules[category]["digits"] = max(1, min(8, int(item.get("digits", rules[category]["digits"]))))
        except (TypeError, ValueError):
            pass
    return rules


def read_numbering_rules():
    return read_engineering_settings().get("numbering_rules", read_numbering_rules_file())


def write_numbering_rules(payload, persist=True):
    rules = read_numbering_rules()
    for category in PHOTO_CATEGORIES:
        item = (payload or {}).get(category) or {}
        template = str(item.get("template") or rules[category]["template"]).strip()
        unit_template = str(item.get("unit_template") or item.get("template") or rules[category].get("unit_template") or template).strip()
        process_template = str(item.get("process_template") or rules[category].get("process_template") or unit_template).strip()
        for tpl in (template, unit_template, process_template):
            if "{seq}" not in tpl:
                raise ValueError("编号规则必须包含 {seq}")
        try:
            start = max(1, int(item.get("start", rules[category]["start"])))
        except (TypeError, ValueError) as exc:
            raise ValueError("起始编号必须是数字") from exc
        try:
            digits = max(1, min(8, int(item.get("digits", rules[category]["digits"]))))
        except (TypeError, ValueError) as exc:
            raise ValueError("编号位数必须是数字") from exc
        rules[category].update({"template": template, "unit_template": unit_template, "process_template": process_template, "start": start, "digits": digits})
    if persist:
        NUMBERING_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        NUMBERING_RULES_PATH.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    return rules


def numbering_start(category):
    rule = read_numbering_rules().get(category) or {}
    try:
        return max(1, int(rule.get("start", 1)))
    except (TypeError, ValueError):
        return 1


def format_numbering_id(project_code, category, sequence):
    category = category if category in PHOTO_CATEGORIES else "construction"
    rule = read_numbering_rules().get(category) or DEFAULT_NUMBERING_RULES[category]
    try:
        digits = max(1, min(8, int(rule.get("digits", 3))))
    except (TypeError, ValueError):
        digits = 3
    template = str(rule.get("template") or DEFAULT_NUMBERING_RULES[category]["template"])
    if "{seq}" not in template:
        template = DEFAULT_NUMBERING_RULES[category]["template"]
    return template.format(
        code=safe_project_code(project_code),
        unit_code=safe_project_code(project_code),
        unit_order=safe_project_code(project_code),
        process_code="",
        process_order="",
        category="JL" if category == "supervision" else "SG",
        seq=f"{int(sequence):0{digits}d}",
    )


def safe_project_code(code):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", str(code or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("项目划分编号不能为空或无效")
    return cleaned[:100]


def current_user():
    username = session.get("username")
    if not username:
        return None
    return {"username": username, "role": "user"}


def login_required_json():
    user = current_user()
    if not user:
        return None, json_error("请先登录后再操作", 401)
    return user, None


@app.route("/api/auth/me")
def auth_me():
    return jsonify({"ok": True, "user": current_user()})


def lan_access_password():
    """局域网访问口令：数据目录 lan_access.json 中配置；未配置则返回空（不限制）。

    本机访问（127.0.0.1）始终免口令，仅局域网请求校验，避免影响桌面软件体验。
    """
    try:
        path = DATA_DIR / "lan_access.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return str(data.get("password") or "").strip()
    except (OSError, ValueError):
        pass
    return ""


def _require_lan_password(payload):
    """局域网请求需校验访问口令；本机或未配置口令时直接放行。"""
    lan_pwd = lan_access_password()
    if lan_pwd and not is_local_setup_request():
        supplied = str(payload.get("password") or "").strip()
        if supplied != lan_pwd:
            raise ValueError("局域网访问口令错误，请联系管理员")


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    payload = request.get_json(silent=True) or request.form
    username = str(payload.get("username", "")).strip()
    if not 2 <= len(username) <= 30:
        return json_error("姓名长度需要为 2-30 个字符")
    try:
        _require_lan_password(payload)
    except ValueError as exc:
        return json_error(str(exc), 401)
    session["username"] = username
    return jsonify({"ok": True, "user": current_user()})


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    payload = request.get_json(silent=True) or request.form
    username = str(payload.get("username", "")).strip()
    if not 2 <= len(username) <= 30:
        return json_error("请输入 2-30 个字符的姓名", 401)
    try:
        _require_lan_password(payload)
    except ValueError as exc:
        return json_error(str(exc), 401)
    session["username"] = username
    return jsonify({"ok": True, "user": current_user()})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.pop("username", None)
    return jsonify({"ok": True})


class AlbumManager:
    """本地影像资料管理：项目划分、批量照片、编号、元数据、导出。"""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._projects_cache = {}
        self._write_locks = {}
        self._write_locks_guard = threading.Lock()

    def _project_write_lock(self, project_code):
        """每个项目一把线程锁，串行化"读-改-写"metadata，防止并发上传丢数据。"""
        key = self._safe_code(project_code)
        with self._write_locks_guard:
            lock = self._write_locks.get(key)
            if lock is None:
                lock = self._write_locks[key] = threading.Lock()
            return lock

    def invalidate_projects_cache(self):
        self._projects_cache = {}

    def _safe_code(self, code):
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", str(code or "").strip())
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
        if not cleaned or cleaned in {".", ".."}:
            raise ValueError("项目划分编码不能为空或无效")
        return cleaned[:100]

    def _project_dir(self, project_code):
        return self.root / self._safe_code(project_code)

    def _photos_dir(self, project_code):
        return self._project_dir(project_code) / "photos"

    def _metadata_path(self, project_code):
        return self._project_dir(project_code) / "metadata.json"

    def _read_metadata(self, project_code):
        path = self._metadata_path(project_code)
        if not path.exists():
            return {
                "project_code": self._safe_code(project_code),
                "project_name": self._safe_code(project_code),
                "keywords": "",
                "source_fields": {},
                "photos": [],
            }
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
        data.setdefault("project_code", self._safe_code(project_code))
        data.setdefault("project_name", data["project_code"])
        data.setdefault("keywords", "")
        data.setdefault("source_fields", {})
        data.setdefault("photos", [])
        return data

    def _write_metadata(self, project_code, data):
        project_dir = self._project_dir(project_code)
        project_dir.mkdir(parents=True, exist_ok=True)
        self._photos_dir(project_code).mkdir(parents=True, exist_ok=True)
        with self._metadata_path(project_code).open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.invalidate_projects_cache()

    def _photo_url(self, project_code, filename):
        return f"/photos/{self._safe_code(project_code)}/{filename}"

    def _thumb_url(self, project_code, filename):
        return f"/thumbs/{self._safe_code(project_code)}/{self._thumb_filename(filename)}"

    # ------------------------------------------------------------ 缩略图
    THUMB_SUFFIX = "thumb_"
    THUMB_MAX_SIDE = 480
    THUMB_QUALITY = 80

    def _thumb_filename(self, filename):
        stem = Path(str(filename)).stem
        return f"{self.THUMB_SUFFIX}{stem}.webp"

    def _find_original(self, project_code, thumb_filename):
        """根据缩略图名反查原图文件路径。"""
        stem = Path(str(thumb_filename)).stem
        if stem.startswith(self.THUMB_SUFFIX):
            stem = stem[len(self.THUMB_SUFFIX):]
        photos_dir = self._photos_dir(project_code)
        for ext in IMAGE_EXTENSIONS:
            candidate = photos_dir / f"{stem}{ext}"
            if candidate.exists():
                return candidate
        return None

    def _ensure_thumbnail(self, project_code, filename):
        """生成缩略图（不存在时才生成）。filename 可为原图名或缩略图名。
        缩略图为最长边 480px 的 WebP，列表用；原图始终保留用于预览/打印。"""
        try:
            from PIL import Image, ImageOps
        except Exception:
            return False
        try:
            photos_dir = self._photos_dir(project_code)
            name = Path(str(filename)).name
            if name.startswith(self.THUMB_SUFFIX):
                thumb_name = name
                original = self._find_original(project_code, thumb_name)
            else:
                thumb_name = self._thumb_filename(name)
                original = photos_dir / name
            thumb_path = photos_dir / thumb_name
            if thumb_path.exists():
                return True
            if original is None or not original.exists():
                return False
            with Image.open(original) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((self.THUMB_MAX_SIDE, self.THUMB_MAX_SIDE), Image.LANCZOS)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                thumb_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(thumb_path, "WEBP", quality=self.THUMB_QUALITY, method=4)
            return True
        except Exception:
            return False

    def _normalize_category(self, category):
        category = str(category or "construction").strip()
        return category if category in PHOTO_CATEGORIES else "construction"

    def _normalize_orientation(self, orientation):
        orientation = str(orientation or "landscape").strip()
        return orientation if orientation in PHOTO_ORIENTATIONS else "landscape"

    def _photo_filename(self, category, archive_id, ext):
        ext = ".jpg" if ext == ".jpeg" else ext
        return f"{category}-{safe_project_code(archive_id)}{ext}"

    def _id_number(self, photo_id):
        text = str(photo_id or "")
        match = re.search(r"(\d+)(?!.*\d)", text)
        if match:
            return int(match.group(1))
        if text.isdigit():
            return int(text)
        return 0

    def _next_id(self, project_code, category, process_name="", process_code=""):
        category = self._normalize_category(category)
        meta = self._read_metadata(project_code)
        used = set()
        candidate_photo = {"process_name": process_name, "process_code": process_code}
        target_scope = self._sequence_scope(meta, candidate_photo, category)
        scope_process_code = str(process_code or "").strip()
        for photo in meta.get("photos", []):
            photo_category = self._normalize_category(photo.get("category"))
            if photo_category == category and self._sequence_scope(meta, photo, category) == target_scope:
                used.add(self._id_number(photo.get("id")))
        photos_dir = self._photos_dir(project_code)
        if photos_dir.exists():
            for file_path in photos_dir.iterdir():
                if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                stem = file_path.stem
                if stem.startswith(f"{category}-"):
                    if target_scope[1] and scope_process_code and scope_process_code not in stem:
                        continue
                    used.add(self._id_number(stem.rsplit("-", 1)[-1]))
                elif category == "construction" and stem.isdigit():
                    used.add(int(stem))
        n = numbering_start(category)
        while n in used:
            n += 1
        return self._archive_id_for_photo(meta, candidate_photo, category, n)

    def _photo_item(self, data, photo):
        item = dict(photo)
        category = self._normalize_category(item.get("category"))
        item["category"] = category
        item["category_label"] = PHOTO_CATEGORY_LABELS[category]
        item.setdefault("title", "")
        item.setdefault("photo_date", "")
        item.setdefault("photographer", "")
        item.setdefault("description", "")
        item.setdefault("process_name", "")
        item.setdefault("process_code", "")
        item.setdefault("uploaded_by", "")
        item["rotation"] = normalize_photo_rotation(item.get("rotation"))
        orientation = self._normalize_orientation(item.get("orientation"))
        item["orientation"] = orientation
        item["orientation_label"] = PHOTO_ORIENTATION_LABELS[orientation]
        # 用原图文件的修改时间做版本号，文件名被复用（如删除后重排）时浏览器不会拿到旧缓存
        version = ""
        try:
            original_path = self._photos_dir(data["project_code"]) / item["filename"]
            version = str(int(original_path.stat().st_mtime))
        except OSError:
            version = ""
        query = f"?v={version}" if version else ""
        item["url"] = self._photo_url(data["project_code"], item["filename"]) + query
        item["thumb_url"] = self._thumb_url(data["project_code"], item["filename"]) + query
        item["project_code"] = data["project_code"]
        item["project_name"] = data.get("project_name", data["project_code"])
        return item

    def _project_unit_order(self, data):
        fields = data.get("source_fields", {}) if isinstance(data, dict) else {}
        for key in ("项目划分顺序", "项目划分行号"):
            try:
                value = int(str(fields.get(key) or "").strip())
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass
        return 1

    def _process_code(self, data, process_name):
        processes = data.get("processes") or (data.get("source_fields") or {}).get("工序名称列表") or []
        if isinstance(processes, str):
            processes = [p.strip() for p in processes.split("、") if p.strip()]
        process_name = str(process_name or "").strip()
        try:
            index = processes.index(process_name) + 1
        except ValueError:
            index = 1
        settings = read_engineering_settings()
        prefix = str(settings.get("process_prefix") or "").strip()
        if not prefix:
            return ""
        digits = int(settings.get("process_digits") or 3)
        return f"{prefix}{index:0{digits}d}"

    def _sequence_scope(self, data, photo, category):
        category = self._normalize_category(category)
        settings = read_engineering_settings()
        process_name = str((photo or {}).get("process_name") or "").strip()
        process_code = str((photo or {}).get("process_code") or "").strip() or self._process_code(data, process_name)
        if data.get("division_type") == "process" and process_code:
            return (category, process_name or process_code)
        return (category, "")

    def _archive_id_for_photo(self, data, photo, category, sequence):
        category = self._normalize_category(category)
        settings = read_engineering_settings()
        rules = settings.get("numbering_rules") or read_numbering_rules()
        rule = rules.get(category) or DEFAULT_NUMBERING_RULES[category]
        try:
            digits = max(1, min(8, int(rule.get("digits", 3))))
        except (TypeError, ValueError):
            digits = 3
        process_name = str((photo or {}).get("process_name") or "").strip()
        process_code = str((photo or {}).get("process_code") or "").strip() or self._process_code(data, process_name)
        unit_order_digits = int(settings.get("unit_order_digits") or 3)
        unit_order = f"{self._project_unit_order(data):0{unit_order_digits}d}"
        use_process = data.get("division_type") == "process" and bool(process_code)
        if settings.get("numbering_mode") == "unit_order":
            if use_process:
                template = rule.get("process_template") or "{unit_order}-{process_code}-{category}{seq}"
            else:
                template = rule.get("unit_template") or "{unit_order}-{category}{seq}"
            unit_code = unit_order
        else:
            template = rule.get("process_template" if use_process else "unit_template") or rule.get("template") or DEFAULT_NUMBERING_RULES[category]["template"]
            unit_code = data.get("display_project_code") or data.get("project_code")
        return str(template).format(
            code=safe_project_code(unit_code),
            unit_code=safe_project_code(unit_code),
            unit_order=unit_order,
            process_code=process_code,
            process_order=process_code,
            category="JY" if category == "supervision" else "SY",
            seq=f"{int(sequence):0{digits}d}",
        )

    def _renumber_category(self, project_code, data, category):
        category = self._normalize_category(category)
        photos_dir = self._photos_dir(project_code)
        matching = [
            photo for photo in data.get("photos", [])
            if self._normalize_category(photo.get("category")) == category
        ]
        staged = []
        counters = {}
        for photo in matching:
            scope = self._sequence_scope(data, photo, category)
            counters[scope] = counters.get(scope, 0) + 1
            index = counters[scope]
            old_filename = photo.get("filename", "")
            old_path = photos_dir / old_filename
            old_thumb = photos_dir / self._thumb_filename(old_filename)
            ext = Path(old_filename).suffix.lower() or ".jpg"
            if photo.get("process_name") and not photo.get("process_code"):
                photo["process_code"] = self._process_code(data, photo.get("process_name"))
            new_id = self._archive_id_for_photo(data, photo, category, index)
            new_filename = self._photo_filename(category, new_id, ext)
            if new_filename == old_filename and str(photo.get("id") or "") == new_id:
                # 顺序未变，无需重命名（刷新自动归位时避免无谓的文件搬移）
                continue
            new_thumb = photos_dir / self._thumb_filename(new_filename)
            temp_path = photos_dir / f".renumber-{index}-{new_filename}"
            if old_path.exists():
                old_path.rename(temp_path)
                staged.append((photo, temp_path, photos_dir / new_filename, new_id, new_filename))
            else:
                staged.append((photo, None, photos_dir / new_filename, new_id, new_filename))
            # 清掉旧缩略图；目标缩略图如有残留也删掉，避免显示成旧照片
            if old_thumb.exists():
                try:
                    old_thumb.unlink()
                except OSError:
                    pass
            if new_thumb.exists():
                try:
                    new_thumb.unlink()
                except OSError:
                    pass

        for photo, temp_path, new_path, new_id, new_filename in staged:
            if temp_path and temp_path.exists():
                if new_path.exists():
                    new_path.unlink()
                temp_path.rename(new_path)
            self._ensure_thumbnail(project_code, new_filename)
            photo["id"] = new_id
            photo["category"] = category
            photo["category_label"] = PHOTO_CATEGORY_LABELS[category]
            photo["filename"] = new_filename

    def create_project(self, project_code, project_name=None, keywords="", source_fields=None, project_order=None):
        original_code = self._safe_code(project_code)
        safe_code = original_code
        if self._metadata_path(safe_code).exists():
            existing = self._read_metadata(safe_code)
            if not project_matches_engineering(existing):
                base_code = self._safe_code(f"{active_engineering_project_id()}__{original_code}")
                safe_code = base_code
                index = 2
                while self._metadata_path(safe_code).exists():
                    existing = self._read_metadata(safe_code)
                    if project_matches_engineering(existing):
                        break
                    safe_code = self._safe_code(f"{base_code}-{index}")
                    index += 1
        data = self._read_metadata(safe_code)
        data["project_code"] = safe_code
        data["display_project_code"] = original_code
        data["project_name"] = str(project_name or data.get("project_name") or safe_code).strip()
        data["keywords"] = str(keywords or data.get("keywords") or "").strip()
        data["engineering_project_id"] = active_engineering_project_id()
        match = match_standard_unit(data["project_name"])
        if source_fields:
            match = {
                "standard_unit_name": source_fields.get("匹配标准单元") or match.get("standard_unit_name", ""),
                "division_type": "process" if source_fields.get("划分类型") == "划分工序单元" else match.get("division_type", "unit"),
                "processes": [p.strip() for p in str(source_fields.get("工序名称列表") or "").split("、") if p.strip()] or match.get("processes", []),
            }
        data["standard_unit_name"] = match.get("standard_unit_name", "")
        data["division_type"] = match.get("division_type") or "unit"
        data["processes"] = list(match.get("processes") or [])
        if project_order is not None:
            try:
                data["project_order"] = int(project_order)
            except (TypeError, ValueError):
                pass
        source_fields = dict(source_fields or data.get("source_fields") or {})
        source_fields.setdefault("单元工程编码", original_code)
        source_fields["内部项目编码"] = safe_code
        source_fields["工程项目ID"] = active_engineering_project_id()
        source_fields["工程项目名称"] = current_engineering_project().get("project_name", "")
        data["source_fields"] = source_fields
        data.setdefault("photos", [])
        self._write_metadata(safe_code, data)
        return data

    def list_projects(self, query="", include_other=False):
        cache_key = (active_engineering_project_id(), str(query or ""), bool(include_other))
        if cache_key in self._projects_cache:
            return self._projects_cache[cache_key]
        projects = []
        query_text = str(query or "").strip().lower()
        for project_dir in self.root.iterdir():
            if not project_dir.is_dir():
                continue
            if project_dir.name.startswith("_"):
                continue
            try:
                data = self._read_metadata(project_dir.name)
            except Exception:
                continue
            if not project_matches_engineering(data):
                continue
            source_fields = data.get("source_fields", {})
            is_other_image = bool(source_fields.get(OTHER_IMAGE_MARKER))
            if is_other_image and not include_other:
                continue
            photos = data.get("photos", [])
            construction_photo_count = sum(1 for photo in photos if photo.get("category") != "supervision")
            supervision_photo_count = sum(1 for photo in photos if photo.get("category") == "supervision")
            item = {
                "project_code": data.get("project_code", project_dir.name),
                "display_project_code": data.get("display_project_code") or source_fields.get("单元工程编码") or data.get("project_code", project_dir.name),
                "project_name": data.get("project_name", project_dir.name),
                "keywords": data.get("keywords", ""),
                "photo_count": len(photos),
                "construction_photo_count": construction_photo_count,
                "supervision_photo_count": supervision_photo_count,
                "latest_upload": photos[-1].get("upload_time", "") if photos else "",
                "source_fields": source_fields,
                "standard_unit_name": data.get("standard_unit_name", ""),
                "division_type": data.get("division_type", "unit"),
                "processes": data.get("processes", []),
                "project_order": data.get("project_order"),
                "is_other_image": is_other_image,
            }
            haystack = json.dumps(item, ensure_ascii=False).lower()
            if not query_text or query_text in haystack:
                projects.append(item)
        result = sorted(projects, key=self._project_sort_key)
        self._projects_cache[cache_key] = result
        return result

    def _project_sort_key(self, item):
        order = item.get("project_order")
        try:
            order_value = int(order)
        except (TypeError, ValueError):
            order_value = 10**12
        return (
            order_value,
            str(item.get("project_code") or "").lower(),
            str(item.get("project_name") or "").lower(),
        )

    def get_project(self, project_code):
        data = self._read_metadata(project_code)
        if not project_matches_engineering(data):
            raise FileNotFoundError("项目不属于当前工程")
        return data

    def get_photos(self, project_code):
        data = self.get_project(project_code)
        return [self._photo_item(data, photo) for photo in data.get("photos", [])]

    def add_photos(self, project_code, files, category="construction", title="", photo_date="", photographer="", description="", uploaded_by="", orientation="landscape", process_name="", process_code="", per_file_meta=None):
        with self._project_write_lock(project_code):
            return self._add_photos_locked(project_code, files, category, title, photo_date, photographer, description, uploaded_by, orientation, process_name, process_code, per_file_meta)

    def _add_photos_locked(self, project_code, files, category="construction", title="", photo_date="", photographer="", description="", uploaded_by="", orientation="landscape", process_name="", process_code="", per_file_meta=None):
        data = self.get_project(project_code)
        category = self._normalize_category(category)
        orientation = self._normalize_orientation(orientation)
        process_name = str(process_name or "").strip()
        process_code = str(process_code or "").strip() or self._process_code(data, process_name)
        photos_dir = self._photos_dir(project_code)
        photos_dir.mkdir(parents=True, exist_ok=True)
        added = []

        for file_storage in files:
            original_name = file_storage.filename or "image.jpg"
            ext = Path(original_name).suffix.lower()
            if ext not in IMAGE_EXTENSIONS:
                raise ValueError(f"只支持 JPG/PNG 图片：{original_name}")

            photo_id = self._next_id(data["project_code"], category, process_name, process_code)
            filename = self._photo_filename(category, photo_id, ext)
            target = photos_dir / filename
            while target.exists():
                photo_id = self._next_id(data["project_code"], category, process_name, process_code)
                filename = self._photo_filename(category, photo_id, ext)
                target = photos_dir / filename

            file_storage.save(target)
            self._ensure_thumbnail(project_code, filename)
            detected = detect_photo_orientation(target)
            if detected:
                orientation = self._normalize_orientation(detected)
            meta = (per_file_meta or {}).get(original_name, {}) or {}
            item = {
                "id": photo_id,
                "category": category,
                "category_label": PHOTO_CATEGORY_LABELS.get(category, category),
                "title": str(meta.get("title") or title or "").strip(),
                "photo_date": str(meta.get("photo_date") or photo_date or "").strip(),
                "photographer": str(photographer or "").strip(),
                "description": str(description or "").strip(),
                "process_name": process_name,
                "process_code": process_code,
                "uploaded_by": str(uploaded_by or "").strip(),
                "orientation": orientation,
                "orientation_label": PHOTO_ORIENTATION_LABELS[orientation],
                "rotation": 0,
                "original_name": original_name,
                "upload_time": now_text(),
                "filename": filename,
                "watermark_text": str(meta.get("watermark_text") or "").strip(),
            }
            data["photos"].append(item)
            self._write_metadata(data["project_code"], data)
            added.append(self._photo_item(data, item))
        return added

    def copy_construction_to_supervision(self, project_code, process_name="", process_code=""):
        """把施工照片复制一份为监理影像，并按监理编号规则重新编号（JY...）。"""
        with self._project_write_lock(project_code):
            return self._copy_to_supervision_locked(project_code, process_name, process_code)

    def _copy_to_supervision_locked(self, project_code, process_name="", process_code=""):
        data = self.get_project(project_code)
        process_name = str(process_name or "").strip()
        process_code = str(process_code or "").strip() or self._process_code(data, process_name)
        photos_dir = self._photos_dir(project_code)
        photos_dir.mkdir(parents=True, exist_ok=True)
        source_photos = [
            photo for photo in data.get("photos", [])
            if self._normalize_category(photo.get("category")) != "supervision"
            and (not process_name or str(photo.get("process_name") or "").strip() == process_name)
        ]
        if not source_photos:
            raise ValueError("该单元没有可用的施工照片")
        # 跳过已复制过的施工照片（按题名+工序去重），重复点击只补缺失的
        existing_supervision = {
            (
                str(p.get("title") or "").strip(),
                str(p.get("process_name") or "").strip(),
            )
            for p in data.get("photos", [])
            if self._normalize_category(p.get("category")) == "supervision"
        }
        source_photos = [
            photo for photo in source_photos
            if (
                str(photo.get("title") or "").strip(),
                str(photo.get("process_name") or "").strip(),
            ) not in existing_supervision
        ]
        if not source_photos:
            raise ValueError("施工照片都已复制到监理影像，无需重复复制")
        added = []
        for photo in source_photos:
            src_path = photos_dir / (photo.get("filename") or "")
            if not src_path.exists():
                continue
            ext = Path(src_path.name).suffix.lower() or ".jpg"
            photo_process_name = str(photo.get("process_name") or "").strip()
            photo_process_code = str(photo.get("process_code") or "").strip() or self._process_code(data, photo_process_name)
            photo_id = self._next_id(data["project_code"], "supervision", photo_process_name, photo_process_code)
            filename = self._photo_filename("supervision", photo_id, ext)
            target = photos_dir / filename
            while target.exists():
                photo_id = self._next_id(data["project_code"], "supervision", photo_process_name, photo_process_code)
                filename = self._photo_filename("supervision", photo_id, ext)
                target = photos_dir / filename
            shutil.copy2(src_path, target)
            self._ensure_thumbnail(project_code, filename)
            detected = detect_photo_orientation(target)
            orientation = self._normalize_orientation(detected or photo.get("orientation"))
            item = {
                "id": photo_id,
                "category": "supervision",
                "category_label": PHOTO_CATEGORY_LABELS["supervision"],
                "title": str(photo.get("title") or "").strip(),
                "photo_date": str(photo.get("photo_date") or "").strip(),
                "photographer": str(photo.get("photographer") or "").strip(),
                "description": str(photo.get("description") or "").strip(),
                "process_name": photo_process_name,
                "process_code": photo_process_code,
                "uploaded_by": str(photo.get("uploaded_by") or "").strip(),
                "orientation": orientation,
                "orientation_label": PHOTO_ORIENTATION_LABELS[orientation],
                "rotation": normalize_photo_rotation(photo.get("rotation")),
                "original_name": str(photo.get("original_name") or src_path.name),
                "upload_time": now_text(),
                "filename": filename,
            }
            data["photos"].append(item)
            added.append(self._photo_item(data, item))
        if not added:
            raise ValueError("施工照片文件不存在，无法复制")
        self._write_metadata(data["project_code"], data)
        return added

    def update_photo(self, project_code, photo_id, **updates):
        with self._project_write_lock(project_code):
            data = self.get_project(project_code)
            target_id = str(photo_id or "").strip()
            if not target_id:
                raise ValueError("照片编号不能为空")
            for photo in data.get("photos", []):
                if str(photo.get("id") or "") == target_id:
                    if "title" in updates:
                        photo["title"] = str(updates.get("title") or "").strip()
                    if "photo_date" in updates:
                        photo["photo_date"] = str(updates.get("photo_date") or "").strip()
                    if "photographer" in updates:
                        photo["photographer"] = str(updates.get("photographer") or "").strip()
                    if "description" in updates:
                        photo["description"] = str(updates.get("description") or "").strip()
                    if "process_name" in updates:
                        photo["process_name"] = str(updates.get("process_name") or "").strip()
                        photo["process_code"] = str(updates.get("process_code") or "").strip() or self._process_code(data, photo["process_name"])
                    if "orientation" in updates:
                        orientation = self._normalize_orientation(updates.get("orientation"))
                        photo["orientation"] = orientation
                        photo["orientation_label"] = PHOTO_ORIENTATION_LABELS[orientation]
                    if "rotation" in updates:
                        photo["rotation"] = normalize_photo_rotation(updates.get("rotation"))
                    self._write_metadata(data["project_code"], data)
                    return self._photo_item(data, photo)
            raise ValueError("照片不存在")

    def reorder_photo(self, project_code, photo_id, direction="up", category=""):
        with self._project_write_lock(project_code):
            data = self.get_project(project_code)
            photos = data.get("photos", [])
            target_id = str(photo_id or "").strip()
            if not target_id:
                raise ValueError("照片编号不能为空")

            target_index = -1
            for index, photo in enumerate(photos):
                if str(photo.get("id") or "") == target_id:
                    target_index = index
                    break
            if target_index < 0:
                raise ValueError("照片不存在")

            target = photos[target_index]
            category = self._normalize_category(category or target.get("category"))
            target_scope = self._sequence_scope(data, target, category)
            group_indexes = [
                index for index, photo in enumerate(photos)
                if self._normalize_category(photo.get("category")) == category
                and self._sequence_scope(data, photo, category) == target_scope
            ]
            try:
                position = group_indexes.index(target_index)
            except ValueError as exc:
                raise ValueError("照片不在当前排序分组内") from exc

            direction = str(direction or "up").strip().lower()
            next_position = position - 1 if direction in {"up", "prev", "previous"} else position + 1
            if next_position < 0 or next_position >= len(group_indexes):
                return self._photo_item(data, target)

            swap_index = group_indexes[next_position]
            photos[target_index], photos[swap_index] = photos[swap_index], photos[target_index]
            self._write_metadata(data["project_code"], data)
            return self._photo_item(data, target)

    def reorder_photos(self, project_code, ordered_ids, category=""):
        with self._project_write_lock(project_code):
            data = self.get_project(project_code)
            photos = data.get("photos", [])
            ordered_ids = [str(item or "").strip() for item in (ordered_ids or []) if str(item or "").strip()]
            if len(ordered_ids) < 2:
                return

            by_id = {str(photo.get("id") or ""): photo for photo in photos}
            ordered = [by_id[photo_id] for photo_id in ordered_ids if photo_id in by_id]
            if len(ordered) != len(ordered_ids):
                raise ValueError("照片排序数据不完整")

            category = self._normalize_category(category or ordered[0].get("category"))
            target_scope = self._sequence_scope(data, ordered[0], category)
            for photo in ordered:
                if self._normalize_category(photo.get("category")) != category or self._sequence_scope(data, photo, category) != target_scope:
                    raise ValueError("只能在同一类影像、同一工序内拖拽排序")

        id_set = set(ordered_ids)
        target_indexes = [index for index, photo in enumerate(photos) if str(photo.get("id") or "") in id_set]
        if len(target_indexes) != len(ordered_ids):
            raise ValueError("照片排序位置不完整")

        for index, photo in zip(target_indexes, ordered):
            photos[index] = photo
        self._write_metadata(data["project_code"], data)

    def auto_sort_piles(self, project_code):
        """灌注桩单元：按桩号分组（每根桩三个工序连体），桩之间按施工完成时间排序，并重新编号。"""
        with self._project_write_lock(project_code):
            data = self.get_project(project_code)
            self._auto_sort_piles_locked(project_code, data)
            return data

    def _auto_sort_piles_locked(self, project_code, data):
        """已持有项目写锁时调用：灌注桩连体排序 + 重新编号。"""
        if not is_pile_unit(data):
            raise ValueError("仅灌注桩类单元支持按桩号自动排序")
        ordered = []
        for category in ("construction", "supervision"):
            photos = [
                photo for photo in data.get("photos", [])
                if self._normalize_category(photo.get("category")) == category
            ]
            if not photos:
                continue
            groups = {}
            for photo in photos:
                pile = photo_pile_number(photo)
                groups.setdefault(pile, []).append(photo)
            dated = []
            undated = []
            unknowns = []
            for pile, group in groups.items():
                if pile is None:
                    # 识别不到桩号的照片固定排最后，保持原相对顺序
                    unknowns.extend(group)
                    continue
                # 组内按工序固定顺序排：钻孔 -> 钢筋笼 -> 混凝土
                group.sort(key=lambda p: pile_process_order(data, p))
                if pile_group_date(data, group):
                    dated.append((pile, group))
                else:
                    undated.append((pile, group))
            dated.sort(key=lambda item: (pile_group_date(data, item[1]), item[0]))
            undated.sort(key=lambda item: item[0])
            for _, group in dated:
                ordered.extend(group)
            for _, group in undated:
                ordered.extend(group)
            ordered.extend(unknowns)
        data["photos"] = ordered
        for category in PHOTO_CATEGORIES:
            self._renumber_category(project_code, data, category)
        self._write_metadata(data["project_code"], data)
        self.invalidate_projects_cache()

    def classify(self, prompt):
        text = str(prompt or "").strip().lower()
        if not text:
            raise ValueError("请输入用于匹配项目划分的提示词")
        tokens = [t for t in re.split(r"[\s,，;；、/\\|]+", text) if t]
        best = None
        best_score = 0
        for project in self.list_projects():
            fields = project.get("source_fields", {})
            haystack = " ".join(
                [
                    project.get("project_code", ""),
                    project.get("project_name", ""),
                    project.get("keywords", ""),
                    json.dumps(fields, ensure_ascii=False),
                ]
            ).lower()
            score = 0
            for word in ["编码", "编号", "代码", "名称", "项目", "项目名称", "工程名称", "单位工程", "分部工程", "分项工程", "单元工程"]:
                if word in haystack:
                    score += 1
            for token in tokens:
                if token in haystack:
                    score += len(token) * 3
            if text in haystack:
                score += len(text) * 5
            if project.get("project_code", "").lower() in text:
                score += 100
            if score > best_score:
                best_score = score
                best = project
        if not best:
            raise ValueError("没有匹配到项目，请先导入项目划分表或换一个提示词")
        return {"project": best, "score": best_score}

    def import_projects_from_xlsx(self, source):
        if load_workbook is None:
            raise RuntimeError("缺少 openpyxl，请先运行：pip install -r requirements.txt")

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"找不到项目划分表：{path}")
        if path.suffix.lower() not in EXCEL_EXTENSIONS:
            raise ValueError("项目划分表只支持 .xlsx/.xlsm")

        wb = load_workbook(path, data_only=True)
        created = 0
        skipped = 0
        seen_codes = self._existing_project_code_keys()
        import_order = 0

        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue
            header_index, headers = self._find_header(rows)
            if header_index is None:
                continue

            carry = {}
            for row_number, raw_row in enumerate(rows[header_index + 1 :], start=header_index + 2):
                row_values = [self._cell_text(v) for v in raw_row[: len(headers)]]
                if not any(row_values):
                    skipped += 1
                    continue

                fields = {}
                for i, header in enumerate(headers):
                    if not header:
                        continue
                    value = row_values[i] if i < len(row_values) else ""
                    if value:
                        carry[header] = value
                    elif self._is_hierarchy_header(header) and header in carry:
                        value = carry[header]
                    fields[header] = value

                if self._is_summary_row(fields):
                    skipped += 1
                    continue

                normalized_fields = self._normalize_project_fields(fields, ws.title)
                project_code = normalized_fields.get("单元工程编码", "")
                project_name = normalized_fields.get("单元工程名称", "")
                if not project_code:
                    skipped += 1
                    continue
                if not project_name:
                    project_name = project_code
                try:
                    safe_code = self._safe_code(project_code)
                except ValueError:
                    skipped += 1
                    continue
                code_key = self._name_key(safe_code)
                if not code_key or code_key in seen_codes:
                    skipped += 1
                    continue

                keywords = " ".join(v for v in normalized_fields.values() if v)
                import_order += 1
                normalized_fields["项目划分顺序"] = str(import_order)
                normalized_fields["项目划分来源表"] = ws.title
                normalized_fields["项目划分行号"] = str(row_number)
                match = match_standard_unit(project_name)
                normalized_fields["匹配标准单元"] = match.get("standard_unit_name", "")
                normalized_fields["划分类型"] = "划分工序单元" if match.get("division_type") == "process" else "不划分工序单元"
                normalized_fields["工序名称列表"] = "、".join(match.get("processes") or [])
                normalized_fields["匹配关键词"] = match.get("match_keyword", "")
                self.create_project(safe_code, project_name, keywords, normalized_fields, import_order)
                created += 1
                seen_codes.add(code_key)

        return {
            "created": created,
            "skipped": skipped,
            "updated": 0,
            "total": created,
            "source": str(path),
        }

    def import_projects_from_records(self, records, source_label="粘贴导入"):
        created = 0
        skipped = 0
        seen_codes = self._existing_project_code_keys()
        import_order = 0

        for row_number, raw_fields in enumerate(records, start=2):
            fields = {}
            for header, value in dict(raw_fields or {}).items():
                header_text = str(header or "").strip().lstrip("\ufeff")
                if header_text:
                    fields[header_text] = self._cell_text(value)
            if not any(fields.values()):
                skipped += 1
                continue
            if self._is_summary_row(fields):
                skipped += 1
                continue

            normalized_fields = self._normalize_project_fields(fields, source_label)
            project_code = normalized_fields.get("单元工程编码") or self._pick_code(normalized_fields)
            project_name = normalized_fields.get("单元工程名称") or self._pick_name(normalized_fields) or project_code
            if not project_code:
                skipped += 1
                continue
            try:
                safe_code = self._safe_code(project_code)
            except ValueError:
                skipped += 1
                continue
            code_key = self._name_key(safe_code)
            if not code_key or code_key in seen_codes:
                skipped += 1
                continue

            keywords = " ".join(v for v in normalized_fields.values() if v)
            import_order += 1
            normalized_fields["项目划分顺序"] = str(import_order)
            normalized_fields["项目划分来源表"] = source_label
            normalized_fields["项目划分行号"] = str(row_number)
            match = match_standard_unit(project_name)
            normalized_fields["匹配标准单元"] = match.get("standard_unit_name", "")
            normalized_fields["划分类型"] = "划分工序单元" if match.get("division_type") == "process" else "不划分工序单元"
            normalized_fields["工序名称列表"] = "、".join(match.get("processes") or [])
            normalized_fields["匹配关键词"] = match.get("match_keyword", "")
            self.create_project(safe_code, project_name, keywords, normalized_fields, import_order)
            created += 1
            seen_codes.add(code_key)

        return {
            "created": created,
            "skipped": skipped,
            "updated": 0,
            "total": created,
            "source": source_label,
        }

    def import_projects_from_text(self, text):
        text = str(text or "").strip()
        if not text:
            raise ValueError("请粘贴项目划分表内容")
        delimiter = "\t" if text.count("\t") >= text.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("粘贴内容缺少表头")
        return self.import_projects_from_records(reader, "粘贴导入")

    def clear_project_division(self):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.root / f"_deleted_projects_{stamp}"
        moved = 0
        for project_dir in list(self.root.iterdir()):
            if not project_dir.is_dir() or project_dir.name.startswith("_"):
                continue
            try:
                data = self._read_metadata(project_dir.name)
            except Exception:
                continue
            if not project_matches_engineering(data):
                continue
            backup_dir.mkdir(parents=True, exist_ok=True)
            target = backup_dir / project_dir.name
            suffix = 1
            while target.exists():
                suffix += 1
                target = backup_dir / f"{project_dir.name}_{suffix}"
            shutil.move(str(project_dir), str(target))
            moved += 1
        self.invalidate_projects_cache()
        return {"deleted": moved, "backup": str(backup_dir) if moved else ""}

    def _cell_text(self, value):
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    def _find_header(self, rows):
        best_index = None
        best_score = 0
        best_headers = []
        for idx, row in enumerate(rows[:30]):
            headers = [self._cell_text(v) for v in row]
            joined = " ".join(headers)
            score = 0
            for word in ["编码", "编号", "名称", "单位工程", "分部工程", "分项工程", "单元工程"]:
                if word in joined:
                    score += 1
            non_empty = sum(1 for h in headers if h)
            if score >= 2 and non_empty >= 2 and score > best_score:
                best_index = idx
                best_score = score
                best_headers = self._dedupe_headers(headers)
        if best_index is not None:
            return best_index, best_headers

        for idx, row in enumerate(rows[:10]):
            values = [self._cell_text(v) for v in row]
            if sum(1 for v in values if v) >= 2:
                return idx, self._dedupe_headers(values)
        return None, []

    def _dedupe_headers(self, headers):
        result = []
        counts = {}
        for i, header in enumerate(headers):
            name = header or f"列{i + 1}"
            counts[name] = counts.get(name, 0) + 1
            if counts[name] > 1:
                name = f"{name}_{counts[name]}"
            result.append(name)
        return result

    def _is_hierarchy_header(self, header):
        normalized_header = "".join(header.split()).lower()
        if any(k in normalized_header for k in ["单位", "分部", "分项", "单元", "工程", "项目", "编码", "编号", "代码", "名称"]):
            return True
        return any(k in header for k in ["单位", "分部", "分项", "单元", "工程", "项目", "编码", "编号", "名称"])

    def _normalized_header(self, header):
        return re.sub(r"\s+", "", str(header or "")).lower()

    def _get_field(self, fields, *needles):
        normalized_needles = [self._normalized_header(needle) for needle in needles]
        for header, value in fields.items():
            if not value:
                continue
            normalized_header = self._normalized_header(header)
            if any(needle and needle in normalized_header for needle in normalized_needles):
                return value
        return ""

    def _is_summary_row(self, fields):
        for header, value in fields.items():
            if not value:
                continue
            text = str(value).strip()
            if text == "合计" or text.startswith("合计"):
                return True
            if "序号" in header and "合计" in text:
                return True
        return False

    def _split_name_code(self, value):
        text = str(value or "").strip()
        if not text:
            return "", ""
        parts = [p.strip() for p in re.split(r"[\r\n]+", text) if p and p.strip()]
        code_pattern = re.compile(r"[A-Za-z]+[A-Za-z0-9-]*-\d(?:[A-Za-z0-9-]*)")
        code = ""
        name_parts = []
        for part in parts:
            match = code_pattern.search(part)
            if match:
                code = match.group(0)
                name = (part[: match.start()] + part[match.end() :]).strip(" -")
                if name:
                    name_parts.append(name)
            else:
                name_parts.append(part)
        if not code:
            match = code_pattern.search(text)
            if match:
                code = match.group(0)
                name = (text[: match.start()] + text[match.end() :]).strip(" \r\n-")
                return name, code
        return " ".join(name_parts).strip(), code

    def _unit_from_sheet(self, sheet_name, unit_code):
        parts = unit_code.split("-")
        inferred_code = "-".join(parts[:2]) if len(parts) >= 2 else ""
        return sheet_name.strip(), inferred_code

    def _normalize_project_fields(self, fields, sheet_name):
        normalized = dict(fields)
        unit_code = self._get_field(fields, "单元工程编码", "单元编码")
        unit_name = self._get_field(fields, "单元工程名称", "单元名称")
        if not unit_code:
            return normalized
        # 单元工程名称里混入编码时自动拆开（如“土方开挖（0+000-0+100） A-3-1-1”）
        if unit_name:
            code_tail = str(unit_code).strip()
            if code_tail and unit_name.endswith(code_tail):
                unit_name = unit_name[: -len(code_tail)].strip(" -")
            elif code_tail and f" {code_tail}" in unit_name:
                unit_name = unit_name.split(f" {code_tail}")[0].strip(" -")
            elif code_tail and f"\n{code_tail}" in unit_name:
                unit_name = unit_name.split(f"\n{code_tail}")[0].strip(" -")
            if not unit_name:
                unit_name = str(unit_code).strip()

        part_combined = self._get_field(fields, "分部工程名称及编码", "分部工程")
        part_name_candidate = self._get_field(fields, "分部工程名称")
        part_code_candidate = self._get_field(fields, "分部工程编码")
        combined_name, combined_code = self._split_name_code(part_combined)
        candidate_name, candidate_code = self._split_name_code(part_name_candidate)
        _, explicit_part_code = self._split_name_code(part_code_candidate)
        part_name = candidate_name or combined_name
        part_code = explicit_part_code or candidate_code or combined_code or part_code_candidate
        if not part_code:
            part_code = "-".join(unit_code.split("-")[:-1])

        unit_project_name = self._get_field(fields, "单位工程名称")
        unit_project_code = self._get_field(fields, "单位工程编码")
        unit_combined = self._get_field(fields, "单位工程名称及编码", "单位工程")
        combined_unit_name, combined_unit_code = self._split_name_code(unit_combined)
        unit_project_name = unit_project_name or combined_unit_name
        unit_project_code = unit_project_code or combined_unit_code
        inferred_unit_name, inferred_unit_code = self._unit_from_sheet(sheet_name, unit_code)
        unit_project_name = unit_project_name or inferred_unit_name
        unit_project_code = unit_project_code or inferred_unit_code

        project_info = read_project_info()
        contract_name = (
            self._get_field(fields, "合同工程名称")
            or project_info.get("project_name")
            or "未填写合同工程"
        )
        normalized.update(
            {
                "合同工程名称": contract_name,
                "单位工程名称": unit_project_name,
                "单位工程编码": unit_project_code,
                "单位工程名称及编码": f"{unit_project_name}\n{unit_project_code}".strip(),
                "分部工程名称": part_name,
                "分部工程编码": part_code,
                "分部工程名称及编码": f"{part_name}\n{part_code}".strip(),
                "单元工程名称": unit_name,
                "单元工程编码": unit_code,
                "来源工作表": sheet_name,
            }
        )
        return normalized

    def _pick_code(self, fields):
        normal_preferred = ["项目划分编码", "项目编码", "单元工程编码", "单元编码", "单位工程编码", "分部工程编码", "分项工程编码", "工程编号", "项目编号", "编号", "编码", "代码"]
        for key in normal_preferred:
            for header, value in fields.items():
                normalized_header = "".join(header.split()).lower()
                if value and key.lower() in normalized_header:
                    return value
        preferred = ["项目划分编码", "单元工程编号", "单位工程编号", "分部工程编号", "分项工程编号", "工程编号", "编号", "编码", "代码"]
        for key in preferred:
            for header, value in fields.items():
                if value and key in header:
                    return value
        for header, value in fields.items():
            if value and ("编号" in header or "编码" in header):
                return value
        return ""

    def _pick_name(self, fields):
        normal_preferred = ["单元工程名称", "项目划分名称", "项目名称", "工程名称", "单位工程名称", "分部工程名称", "分项工程名称", "单位工程", "分部工程", "分项工程", "名称"]
        for key in normal_preferred:
            for header, value in fields.items():
                normalized_header = "".join(header.split()).lower()
                if value and key.lower() in normalized_header:
                    return value
        preferred = ["单元工程名称", "项目划分名称", "项目名称", "工程名称", "单位工程", "分部工程", "分项工程", "名称"]
        for key in preferred:
            for header, value in fields.items():
                if value and key in header:
                    return value
        for header, value in fields.items():
            if value and "名称" in header:
                return value
        return ""

    def _name_key(self, name):
        return re.sub(r"\s+", "", str(name or "")).lower()

    def _existing_project_code_keys(self):
        keys = set()
        for project in self.list_projects():
            key = self._name_key(project.get("project_code"))
            if key:
                keys.add(key)
        return keys

    def export_csv(self, project_code):
        data = self._read_metadata(project_code)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["项目编码", "项目名称", "照片编号", "照片文件", "原文件名", "描述", "上传时间"])
        for photo in data.get("photos", []):
            writer.writerow(
                [
                    data["project_code"],
                    data.get("project_name", ""),
                    photo.get("id", ""),
                    photo.get("filename", ""),
                    photo.get("original_name", ""),
                    photo.get("description", ""),
                    photo.get("upload_time", ""),
                ]
            )
        return output.getvalue().encode("utf-8-sig")

    def export_zip(self, project_code):
        data = self._read_metadata(project_code)
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("metadata.json", json.dumps(data, ensure_ascii=False, indent=2))
            zf.writestr("metadata.csv", self.export_csv(project_code))
            photos_dir = self._photos_dir(project_code)
            watermark = watermark_text_for_user()
            for photo in data.get("photos", []):
                file_path = photos_dir / photo.get("filename", "")
                if not file_path.exists():
                    continue
                if watermark:
                    out = add_watermark_to_image(file_path, watermark)
                    if out is not None:
                        zf.writestr(f"photos/{file_path.name}", out.getvalue())
                        continue
                zf.write(file_path, f"photos/{file_path.name}")
        memory.seek(0)
        return memory

    def export_engineering_package(self):
        engineering_project = current_engineering_project()
        projects = self.list_projects(include_other=True)
        package = {
            "format": "engineering-image-package",
            "version": 1,
            "exported_at": now_text(),
            "engineering_project": engineering_project,
            "projects": [],
        }
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as zf:
            for project in projects:
                code = project.get("project_code")
                if not code:
                    continue
                data = self.get_project(code)
                package["projects"].append(data)
                photos_dir = self._photos_dir(code)
                watermark = watermark_text_for_user()
                for photo in data.get("photos", []):
                    file_path = photos_dir / photo.get("filename", "")
                    if not file_path.exists():
                        continue
                    if watermark:
                        out = add_watermark_to_image(file_path, watermark)
                        if out is not None:
                            zf.writestr(f"photos/{code}/{file_path.name}", out.getvalue())
                            continue
                    zf.write(file_path, f"photos/{code}/{file_path.name}")
            zf.writestr("package.json", json.dumps(package, ensure_ascii=False, indent=2))
        memory.seek(0)
        return memory

    def import_engineering_package(self, package_path):
        imported_projects = 0
        imported_photos = 0
        current_id = active_engineering_project_id()
        with zipfile.ZipFile(package_path) as zf:
            try:
                package = json.loads(zf.read("package.json").decode("utf-8-sig"))
            except KeyError as exc:
                raise ValueError("资料包缺少 package.json") from exc
            if package.get("format") != "engineering-image-package":
                raise ValueError("资料包格式不正确")
            for data in package.get("projects", []):
                if not isinstance(data, dict):
                    continue
                code = self._safe_code(data.get("project_code") or "")
                source_fields = dict(data.get("source_fields") or {})
                source_fields["工程项目ID"] = current_id
                source_fields["工程项目名称"] = current_engineering_project().get("project_name", "")
                data["project_code"] = code
                data["engineering_project_id"] = current_id
                data["source_fields"] = source_fields
                project_dir = self._project_dir(code)
                photos_dir = self._photos_dir(code)
                photos_dir.mkdir(parents=True, exist_ok=True)
                for photo in data.get("photos", []):
                    filename = secure_filename(photo.get("filename") or "")
                    if not filename:
                        continue
                    source_name = f"photos/{code}/{filename}"
                    if source_name not in zf.namelist():
                        continue
                    target = photos_dir / filename
                    suffix = 1
                    original_target = target
                    while target.exists():
                        suffix += 1
                        target = original_target.with_name(f"{original_target.stem}_{suffix}{original_target.suffix}")
                    with zf.open(source_name) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    photo["filename"] = target.name
                    imported_photos += 1
                project_dir.mkdir(parents=True, exist_ok=True)
                self._write_metadata(code, data)
                imported_projects += 1
        return {"imported_projects": imported_projects, "imported_photos": imported_photos}

    def dashboard(self, include_other=False):
        projects = self.list_projects(include_other=include_other)
        photo_count = sum(p["photo_count"] for p in projects)
        construction_photo_count = sum(p.get("construction_photo_count", 0) for p in projects)
        supervision_photo_count = sum(p.get("supervision_photo_count", 0) for p in projects)
        latest = ""
        for project in projects:
            if project["latest_upload"] and project["latest_upload"] > latest:
                latest = project["latest_upload"]
        return {
            "project_count": len(projects),
            "photo_count": photo_count,
            "construction_photo_count": construction_photo_count,
            "supervision_photo_count": supervision_photo_count,
            "latest_upload": latest,
        }


manager = AlbumManager(ALBUMS_DIR)


def app_license_status():
    status = licensing.license_status()
    photo_count = manager.dashboard(include_other=True).get("photo_count", 0)
    trial_active = not status.get("ok")
    trial_period_active = bool(status.get("trial_period_active"))
    status.update({
        "trial_limit": status.get("trial_valid_days", 30),
        "photo_count": photo_count,
        "trial_active": trial_active,
        "trial_remaining": None if status.get("ok") else max(0, int(status.get("trial_days_remaining") or 0)),
        "upload_locked": (not status.get("ok")) and not trial_period_active,
    })
    return status


def _read_share_points():
    if not SHARE_POINTS_PATH.exists():
        return {"events": []}
    try:
        with SHARE_POINTS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("events", [])
            return data
    except Exception:
        pass
    return {"events": []}


def _write_share_points(data):
    SHARE_POINTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SHARE_POINTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _share_target_key(value):
    text = re.sub(r"\s+", "", str(value or "").strip().lower())
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def share_points_status():
    data = _read_share_points()
    events = data.get("events") if isinstance(data.get("events"), list) else []
    valid_events = [event for event in events if event.get("points")]
    total = sum(int(event.get("points") or 0) for event in valid_events)
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = sum(1 for event in valid_events if str(event.get("created_at", "")).startswith(today))
    return {
        "total_points": total,
        "points_per_share": SHARE_POINTS_PER_PERSON,
        "redeem_threshold": SHARE_POINTS_REDEEM_THRESHOLD,
        "daily_limit": SHARE_POINTS_DAILY_LIMIT,
        "today_count": today_count,
        "today_remaining": max(0, SHARE_POINTS_DAILY_LIMIT - today_count),
        "redeemable_count": total // SHARE_POINTS_REDEEM_THRESHOLD,
        "lifetime_price": LIFETIME_LICENSE_PRICE,
        "machine_id": licensing.machine_id(),
        "events": valid_events[-20:],
    }


def add_share_points(target, note=""):
    data = _read_share_points()
    events = data.get("events") if isinstance(data.get("events"), list) else []
    target_text = str(target or "").strip()
    target_key = _share_target_key(target_text)
    if not target_key:
        raise ValueError("请输入分享对象，例如微信群名、好友昵称或手机号后四位")
    if any(event.get("target_key") == target_key for event in events):
        raise ValueError("这个分享对象已记录过，不能重复积分")
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = sum(1 for event in events if event.get("points") and str(event.get("created_at", "")).startswith(today))
    if today_count >= SHARE_POINTS_DAILY_LIMIT:
        raise ValueError(f"今日最多记录 {SHARE_POINTS_DAILY_LIMIT} 次分享，明天再继续")
    event = {
        "created_at": now_text(),
        "target_hint": target_text[:24],
        "target_key": target_key,
        "points": SHARE_POINTS_PER_PERSON,
        "note": str(note or "").strip()[:80],
        "machine_id": licensing.machine_id(),
    }
    events.append(event)
    data["events"] = events[-500:]
    _write_share_points(data)
    return share_points_status()


def print_layout_from_request():
    layout = str(request.args.get("layout") or read_engineering_settings().get("print_layout") or "landscape").strip().lower()
    return "portrait" if layout == "portrait" else "landscape"


def print_page_size_from_request():
    try:
        value = int(request.args.get("page_size") or read_engineering_settings().get("print_page_size") or 4)
    except (TypeError, ValueError):
        value = 4
    return value if value in {1, 2, 4} else 4


def print_photo_ids_from_request():
    raw = str(request.args.get("ids") or "").strip()
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def photo_detail_rows(project, photo):
    settings = read_engineering_settings()
    fields = settings.get("photo_detail_fields") or DEFAULT_ENGINEERING_SETTINGS["photo_detail_fields"]
    source = {}
    source.update(project.get("source_fields", {}) if isinstance(project, dict) else {})
    source.update(project or {})
    source.update(photo or {})
    rows = []
    for field in fields:
        label = str(field.get("label") or "").strip()
        key = str(field.get("source") or "").strip()
        if not label:
            continue
        value = str(field.get("value") or "").strip() if key == "custom" else str(source.get(key) or "").strip()
        if not value:
            continue
        rows.append({"label": label, "value": value})
    return rows


def is_pile_unit(data):
    """判断是否为灌注桩类单元（如 钻孔灌注桩单元工程），用于连体排序。"""
    text = " ".join([
        str(data.get("standard_unit_name") or ""),
        str(data.get("project_name") or ""),
    ])
    return "灌注桩" in text


def photo_pile_number(photo):
    """从照片题名/原始文件名解析桩号，返回排序元组或 None。

    支持：1#桩、2#、桩3、4号桩 -> (N,)；
    Q11-1、右岸Q14-15、2-27#、14-15 -> (N1, N2)。
    """
    candidates = [
        str(photo.get("title") or "").strip(),
        str(photo.get("original_name") or "").strip(),
        Path(str(photo.get("filename") or "")).stem,
    ]
    dash_pattern = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]*\d{1,3})\s*[-—–－]\s*(\d{1,3})(?![\d])")
    simple_patterns = (
        re.compile(r"(\d+)\s*[#＃号]\s*桩"),
        re.compile(r"(\d+)\s*[#＃号]"),
        re.compile(r"桩\s*(\d+)"),
    )
    for text in candidates:
        if not text:
            continue
        m = dash_pattern.search(text)
        if m:
            left = re.search(r"(\d+)\s*$", m.group(1))
            if left:
                return (int(left.group(1)), int(m.group(2)))
        for pattern in simple_patterns:
            m = pattern.search(text)
            if m:
                return (int(m.group(1)),)
    return None


def pile_process_order(data, photo):
    """灌注桩工序排序：钻孔 -> 钢筋笼 -> 混凝土；工序从照片的工序字段或题名识别。"""
    process_name = str(photo.get("process_name") or "").strip()
    processes = data.get("processes") or []
    if isinstance(processes, str):
        processes = [p.strip() for p in processes.split("、") if p.strip()]
    if process_name:
        try:
            return processes.index(process_name)
        except ValueError:
            pass
    text = " ".join([
        process_name,
        str(photo.get("title") or ""),
        str(photo.get("original_name") or ""),
    ])
    for keyword, order in (("钻孔", 0), ("钢筋笼", 1), ("钢筋", 1), ("混凝土", 2), ("浇筑", 2)):
        if keyword in text:
            return order
    return 10 + len(processes)


def pile_group_date(data, group):
    """桩的时间排序键：取该桩最后一道工序（浇筑/混凝土）的拍摄日期。"""
    entries = [
        (pile_process_order(data, p), str(p.get("photo_date") or "").strip())
        for p in group
    ]
    entries = [(order, date) for order, date in entries if date]
    if not entries:
        return ""
    last_order = max(order for order, _ in entries)
    return min(date for order, date in entries if order == last_order)


def pile_photos_key(data, photos, photo):
    """连体排序基础键：桩的施工完成日期（最后工序日期）-> 桩号。"""
    pile = photo_pile_number(photo)
    group = [item for item in photos if photo_pile_number(item) == pile] if pile is not None else []
    group_date = pile_group_date(data, group) if group else ""
    return (
        0 if (pile is not None and group_date) else 1,
        group_date,
        pile if pile is not None else 10 ** 12,
    )


def enrich_print_photos(project, photos):
    result = []
    processes = project.get("processes") or []
    process_order = {name: index for index, name in enumerate(processes)}
    for photo in photos:
        item = dict(photo)
        item["detail_rows"] = photo_detail_rows(project, item)
        item["_process_order"] = process_order.get(item.get("process_name"), 9999)
        result.append(item)
    if is_pile_unit(project):
        # 灌注桩：每根桩三个工序连体，桩之间按拍摄时间排序（监理跟随施工同一规则）
        return sorted(result, key=lambda p: pile_photos_key(project, result, p) + (
            pile_process_order(project, p),
            manager._id_number(p.get("id")),
            str(p.get("upload_time") or ""),
        ))
    return sorted(result, key=lambda p: (p.get("_process_order", 9999), p.get("process_name", ""), manager._id_number(p.get("id")), p.get("upload_time", "")))


PHOTO_5IN_LANDSCAPE = (127.0, 89.0)  # 5 寸横版（mm），竖版照片打印时自动转 90° 横放
PRINT_FIXED_GAP = 2.0


def _print_caption_h(photo, single_line=False):
    """照片下方说明文字高度：字号加大、最多两行；4 张/页时压缩排版但仍支持两行。"""
    rows = len(photo.get("detail_rows") or [])
    if rows <= 0:
        return 0.0
    if single_line:
        return 4.9
    # 每行最多折成两行，行高压小
    return round(max(6.0, rows * 4.8 + 1.0), 1)


def layout_fixed_photo_pages(photos, layout="landscape", page_size=2):
    """按 5 寸横版固定尺寸自动排版：
    所有照片都按 127x89mm 打印，竖版照片自动加 90° 旋转横放；
    说明文字排在照片下方（照片之外）；
    每页 2 张（标准页边距、说明多行）或每页 4 张（2x2，最小页边距、说明一行）；
    返回 [{照片信息..., _left, _top, _w, _h, _block_h, _caption_h, _rotate}, ...] 的页列表。
    """
    try:
        page_size = int(page_size)
    except (TypeError, ValueError):
        page_size = 2
    if page_size not in (1, 2, 4):
        page_size = 2
    single_line = page_size == 4
    if page_size == 4:
        # 4 张/页只支持 A4 横版 + 最小页边距
        layout = "landscape"
        page_w, page_h = 283.0, 190.0
    elif layout == "portrait":
        page_w, page_h = 166.0, 242.0
    else:
        page_w, page_h = 256.0, 158.0
    pages = []
    current = []
    row_y = 0.0
    row_h = 0.0
    x = 0.0
    for photo in photos:
        width, height = PHOTO_5IN_LANDSCAPE
        caption_h = _print_caption_h(photo, single_line=single_line)
        block_h = height + caption_h
        rotate = int(photo.get("rotation") or 0) % 360
        if str(photo.get("orientation") or "landscape") == "portrait":
            rotate = (rotate + 90) % 360
        if x > 0 and x + width > page_w + 0.5:
            row_y += row_h + PRINT_FIXED_GAP
            x = 0.0
            row_h = 0.0
        if row_y + block_h > page_h + 0.5 and current:
            pages.append(current)
            current = []
            row_y = 0.0
            x = 0.0
            row_h = 0.0
        item = dict(photo)
        item["_left"] = round(x, 1)
        item["_top"] = round(row_y, 1)
        item["_w"] = width
        item["_h"] = height
        item["_block_h"] = round(block_h, 1)
        item["_caption_h"] = caption_h
        item["_rotate"] = rotate
        current.append(item)
        if page_size == 1:
            pages.append(current)
            current = []
            row_y = 0.0
            x = 0.0
            row_h = 0.0
            continue
        x += width + PRINT_FIXED_GAP
        row_h = max(row_h, block_h)
    if current:
        pages.append(current)
    return pages


PHOTO_STATISTICS_COLUMNS = [
    "序号",
    "单元编码",
    "单元名称",
    "影像类别",
    "工序",
    "照片编号",
    "照片名称",
    "原文件名",
    "拍摄时间",
    "摄影者",
    "描述",
    "备注",
]


def export_photo_statistics_xlsx(codes=""):
    """按单元导出照片统计表：每个单元一行序号，列出照片编号、照片名称等信息。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    except Exception as exc:
        raise RuntimeError(f"缺少 openpyxl，请先运行：pip install -r requirements.txt（{exc}）")
    selected = {str(code).strip() for code in str(codes or "").split(",") if str(code).strip()}
    projects = manager.list_projects(include_other=False)
    if selected:
        projects = [item for item in projects if str(item.get("project_code") or "") in selected]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "照片统计表"
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4472C4")
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    sheet.append(PHOTO_STATISTICS_COLUMNS)
    for cell in sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    row_index = 2
    for project in projects:
        code = project.get("project_code") or ""
        data = manager.get_project(code)
        source_fields = data.get("source_fields") or {}
        display_code = data.get("display_project_code") or source_fields.get("单元工程编码") or code
        unit_name = data.get("project_name") or code
        photos = list(data.get("photos") or [])
        if is_pile_unit(data):
            # 灌注桩：每根桩三个工序连体，桩之间按拍摄时间排序
            photos.sort(key=lambda p: (
                0 if manager._normalize_category(p.get("category")) == "construction" else 1,
            ) + pile_photos_key(data, photos, p) + (
                pile_process_order(data, p),
                manager._id_number(p.get("id")),
            ))
        else:
            photos.sort(key=lambda p: (
                0 if manager._normalize_category(p.get("category")) == "construction" else 1,
                str(p.get("process_name") or ""),
                manager._id_number(p.get("id")),
            ))
        for index, photo in enumerate(photos, start=1):
            category = manager._normalize_category(photo.get("category"))
            title = str(photo.get("title") or "").strip()
            original_name = str(photo.get("original_name") or photo.get("filename") or "").strip()
            sheet.append([
                index,
                display_code,
                unit_name,
                PHOTO_CATEGORY_LABELS.get(category, category),
                str(photo.get("process_name") or "").strip(),
                str(photo.get("id") or "").strip(),
                title or original_name,
                original_name,
                str(photo.get("photo_date") or "").strip(),
                str(photo.get("photographer") or "").strip(),
                str(photo.get("description") or "").strip(),
                "",
            ])
            for cell in sheet[row_index]:
                cell.border = border
                cell.alignment = Alignment(vertical="center")
            row_index += 1
    sheet.freeze_panes = "A2"
    for column in sheet.columns:
        header = column[0]
        max_len = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[header.column_letter].width = min(max(max_len + 2, 8), 40)
    memory = io.BytesIO()
    workbook.save(memory)
    memory.seek(0)
    return memory


def expired_license_response(action):
    status = app_license_status()
    if status.get("upload_locked"):
        return f"一个月试用期已到期，无法{action}，请联系管理员继续使用。", 403
    return None


def validate_upload_files(files):
    valid = []
    invalid = []
    for file_storage in files:
        if not file_storage or not file_storage.filename:
            continue
        original_name = file_storage.filename or "image.jpg"
        ext = Path(original_name).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            valid.append(file_storage)
        else:
            invalid.append(original_name)
    if invalid:
        sample = "、".join(invalid[:5])
        suffix = "等" if len(invalid) > 5 else ""
        raise ValueError(f"只支持 JPG/PNG 图片：{sample}{suffix}")
    if not valid:
        raise ValueError("请选择要上传的 JPG/PNG 图片")
    return valid


def _watermark_meta_for_upload(file_storage):
    """对单张照片做水印文字 OCR，返回 {title, photo_date, watermark_text} 或 None。"""
    if not file_storage:
        return None
    try:
        file_storage.stream.seek(0)
        image_bytes = file_storage.stream.read()
        fields = watermark_ocr.recognize_watermark(image_bytes)
        file_storage.stream.seek(0)
    except Exception:
        return None
    meta = {}
    if fields.get("title"):
        meta["title"] = fields["title"]
    if fields.get("photo_date"):
        meta["photo_date"] = fields["photo_date"]
    if fields.get("watermark_text"):
        meta["watermark_text"] = fields["watermark_text"]
    return meta or None


def _enrich_watermark_metadata(files, shared_title, shared_date, enabled, form_title="", form_date=""):
    """对每张照片做水印 OCR，返回 (per_file_meta, shared_title, shared_date)。

    规则：表单显式填了题名/日期时保留（不被水印覆盖）；否则每张照片用自己水印文字补全，
    第一张识别到的水印回填到共享值做兜底（满足上传的必填日期校验）。
    """
    per_file_meta = {}
    if not enabled:
        return per_file_meta, shared_title, shared_date
    for file_storage in files:
        meta = _watermark_meta_for_upload(file_storage)
        if not meta:
            continue
        if form_title:
            meta.pop("title", None)
        if form_date:
            meta.pop("photo_date", None)
        if not meta:
            continue
        per_file_meta[file_storage.filename] = meta
        if not form_title and not shared_title and meta.get("title"):
            shared_title = meta["title"]
        if not form_date and not shared_date and meta.get("photo_date"):
            shared_date = meta["photo_date"]
    return per_file_meta, shared_title, shared_date


def normalize_match_text(value):
    return re.sub(r"[\s\-_.()（）【】\[\]{}?？]+", "", str(value or "").lower())


def project_match_candidates(project):
    fields = project.get("source_fields") or {}
    raw_values = [
        project.get("project_code", ""),
        project.get("project_name", ""),
        fields.get("单元工程编码", ""),
        fields.get("单元工程名称", ""),
    ]
    values = []
    seen = set()
    for raw in raw_values:
        text = str(raw or "").strip()
        key = normalize_match_text(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        values.append((text, key))
    return values


def match_project_by_filename(filename):
    stem = Path(filename or "").stem
    file_key = normalize_match_text(stem)
    if not file_key:
        return None
    best = None
    best_score = 0
    for project in manager.list_projects():
        code = str(project.get("project_code") or "").strip()
        if not code or not manager._metadata_path(code).exists():
            continue
        for raw, key in project_match_candidates(project):
            if len(key) < 2:
                continue
            score = 0
            if key == file_key:
                score = 100000 + len(key)
            elif key in file_key:
                is_code = raw == code or re.search(r"[A-Za-z0-9]", raw)
                score = (60000 if is_code else 30000) + len(key)
            elif file_key in key and len(file_key) >= 4:
                score = 10000 + len(file_key)
            if score > best_score:
                best_score = score
                best = project
    return best if best_score else None


FREE_PHOTO_LIMIT = 300  # 免费版全部照片合计上限
WATERMARK_TEXT = "乐嵘聚合"  # 免费版打印/导出水印文字


def watermark_text_for_user():
    """免费版返回水印文字，会员返回空（无水印）。"""
    return "" if is_member_user() else WATERMARK_TEXT


def add_watermark_to_image(file_path, text=WATERMARK_TEXT):
    """在图片上叠加半透明斜向水印，返回带水印的 BytesIO（供免费版导出用）。
    text 为空或图片处理失败时返回原始文件字节。"""
    if not text:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.open(file_path)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        w, h = img.size
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font_size = max(24, int(w / 10))
        try:
            font = ImageFont.truetype("msyh.ttc", font_size)
        except Exception:
            try:
                font = ImageFont.truetype("simhei.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()
        # 在透明层上按网格画多个水印文字，再整层旋转合成，形成斜向水印
        step_x = int(w * 0.85)
        step_y = int(font_size * 2.6)
        for y in range(-font_size * 2, h + font_size, step_y):
            for x in range(-w, w + step_x, step_x):
                draw.text((x, y), text, font=font, fill=(255, 0, 0, 90))
        rotated = overlay.rotate(25, expand=False, resample=Image.BICUBIC)
        combined = Image.alpha_composite(img, rotated)
        out = io.BytesIO()
        combined.convert("RGB").save(out, format="JPEG", quality=92)
        out.seek(0)
        return out
    except Exception:
        return None


def is_member_user():
    """会员判定：登录的云账号有有效授权，或本机已有有效授权码，均视为会员。"""
    try:
        mem = cloud_client.membership_status()
        if mem.get("is_member"):
            return True
    except Exception:
        pass
    return bool(app_license_status().get("ok"))


# 云预览自动同步：每项目最多同步的缩略图数（控制服务器负载）
CLOUD_SYNC_THUMB_CAP = 60


def _build_cloud_sync_payload(max_thumbs=CLOUD_SYNC_THUMB_CAP):
    """枚举本机工程项目 + 缩略图，构造云预览同步 payload。"""
    import base64 as _b64

    projects_payload = []
    try:
        items = manager.list_projects(include_other=True)
    except Exception:
        return []
    for item in items:
        code = str(item.get("project_code") or "")
        if not code:
            continue
        source = item.get("source_fields") or {}
        unit_name = str(source.get("单位工程名称") or source.get("单位名称") or "")
        part_name = str(source.get("分部工程名称") or source.get("分部名称") or "")
        thumbs = []
        try:
            photos = manager.get_photos(code)
            for photo in photos[:max_thumbs]:
                fname = str(photo.get("filename") or "")
                if not fname:
                    continue
                thumb_rel = manager._thumb_filename(fname)
                thumb_path = manager._photos_dir(code) / thumb_rel
                if thumb_path.exists():
                    try:
                        b64 = _b64.b64encode(thumb_path.read_bytes()).decode("ascii")
                        if len(b64) > cloud_client.CLOUD_THUMB_MAX_B64:
                            continue
                        thumbs.append({"photo_name": fname, "thumb_b64": b64})
                    except Exception:
                        continue
        except Exception:
            pass
        # 只同步有照片的项目（空项目不同步，避免无用数据）
        if not thumbs:
            continue
        projects_payload.append({
            "project_code": code,
            "project_name": str(item.get("project_name") or ""),
            "unit_name": unit_name,
            "part_name": part_name,
            "thumb_count": len(thumbs),
            "thumbs": thumbs,
        })
    return projects_payload


def sync_cloud_preview_async():
    """后台线程：把本机项目缩略图+编号同步到服务器云预览（账号隔离）。

    未登录云账号时，若配置了 ALBUM_CLOUD_AUTO_USER/ALBUM_CLOUD_AUTO_PASS，
    自动登录后同步（供服务器电脑无人工登录时自动上传云预览）。
    """
    def worker():
        try:
            payload = _build_cloud_sync_payload()
            if not payload:
                return
            # 未登录时尝试用环境变量账号自动登录
            if not cloud_client.membership_status().get("logged_in"):
                auto_user = os.environ.get("ALBUM_CLOUD_AUTO_USER", "").strip()
                auto_pass = os.environ.get("ALBUM_CLOUD_AUTO_PASS", "")
                if auto_user and auto_pass:
                    cloud_client.login(auto_user, auto_pass)
            # 单项目循环同步，避免大请求被服务器拒绝
            for proj in payload:
                cloud_client.sync_projects([proj])
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


def free_photo_over_limit(incoming_count):
    """免费版：全部照片合计 >= FREE_PHOTO_LIMIT 时拦截上传。返回剩余额度或 None。"""
    photo_count = app_license_status().get("photo_count", 0)
    remaining = max(0, FREE_PHOTO_LIMIT - photo_count)
    if incoming_count > remaining:
        return remaining
    return None


def trial_upload_limit_response(incoming_count):
    # 会员：不限量
    if is_member_user():
        return None
    # 免费版：先查 300 张上限
    remaining = free_photo_over_limit(incoming_count)
    if remaining is not None:
        return jsonify({
            "ok": False,
            "error": f"免费版照片总上限 {FREE_PHOTO_LIMIT} 张，已达上限，无法再上传。升级会员可无限使用。",
            "license_required": True,
            "photo_limit_reached": True,
            "free_photo_limit": FREE_PHOTO_LIMIT,
            "remaining": remaining,
        }), 403
    # 免费版：保留试用期到期逻辑
    status = app_license_status()
    if status.get("upload_locked"):
        return jsonify({
            "ok": False,
            "error": "试用期已到期，无法上传照片。升级会员可继续使用。",
            "license_required": True,
            "expired": True,
        }), 403
    return None


def read_other_images():
    if not OTHER_IMAGES_PATH.exists():
        return {"nodes": []}
    try:
        data = json.loads(read_text_with_fallback(OTHER_IMAGES_PATH))
    except (OSError, json.JSONDecodeError, ValueError):
        backup = OTHER_IMAGES_PATH.with_name(
            f"{OTHER_IMAGES_PATH.stem}.broken_{datetime.now().strftime('%Y%m%d_%H%M%S')}{OTHER_IMAGES_PATH.suffix}"
        )
        try:
            shutil.copy2(OTHER_IMAGES_PATH, backup)
        except OSError:
            pass
        return {"nodes": []}
    nodes = data.get("nodes", [])
    return {"nodes": nodes if isinstance(nodes, list) else []}


def write_other_images(data):
    OTHER_IMAGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OTHER_IMAGES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def natural_sort_key(text):
    """自然排序键：数字段按数值优先、文字段随后，段类型一致避免 int/str 混比崩溃。"""
    key = []
    for part in re.split(r"(\d+)", str(text or "")):
        if part.isdigit():
            key.append((0, int(part)))
        elif part:
            key.append((1, part.lower()))
    return key


def _extract_date_from_text(text):
    """从文件名提取日期，支持多种格式，返回 (ISO日期, 去掉日期后的文本)。
    - 2025年9月30日 / 2025-09-30 / 2025.9.30 / 2025/09/30
    - 20250930（8位连续）
    - IMG_20250930_143000（手机拍摄）
    - 9月30日（省略年份，取当前年）
    """
    year = datetime.now().year
    m = re.search(r"(20\d{2})\s*[年.\-/]\s*(\d{1,2})\s*[月.\-/]\s*(\d{1,2})\s*日?", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", text.replace(m.group(0), "", 1)
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", text.replace(m.group(0), "", 1)
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        return f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}", text.replace(m.group(0), "", 1)
    return "", text


def parse_photo_name_parts(filename):
    """从照片文件名解析“简要描述”和“拍摄时间”。
    例如：001号2025年9月30日排水沟20原貌.jpg -> title=排水沟20原貌, photo_date=2025-09-30
    支持：2025-09-30排水沟.jpg、20250930钻孔.jpg、IMG_20250930_143000.jpg、9月30日钻孔.jpg
    """
    stem = Path(filename or "").stem
    text = str(stem).strip()
    photo_date, text = _extract_date_from_text(text)
    # 去掉 IMG_ / VID_ / DSC_ 等相机前缀；IMG_20250930_143000 里的时间戳也去掉
    text = re.sub(r"^(?:IMG|VID|DSC|PANO)_?", "", text, flags=re.I)
    text = re.sub(r"^[\s_\-]?\d{6}\s*$", "", text)  # 残留的 HHMMSS 时间戳
    text = re.sub(r"^\s*\d+[号#\s]*", "", text)
    text = re.sub(r"^[\s_\-—–·.]+|[\s_\-—–·.]+$", "", text)
    # 无说明文字时返回空（而不是回退整个文件名），日期仍可用
    return text, photo_date


def folder_core_name(name):
    """把文件夹/单元名称归一化成可比较的核心词：
    去掉空白、括号内容、桩号（如 0+000~0+500、K0+000—K0+255）。"""
    text = str(name or "").strip()
    text = re.sub(r"[★☆\s]+", "", text)
    text = re.sub(r"（[^）]*）|\([^)]*\)", "", text)
    text = re.sub(r"[Kk]?\d+\+\d+[—\-~～]?[Kk]?\d*\+\d*", "", text)
    text = re.sub(r"[Kk]?\d+\+\d+", "", text)
    return text


def match_folder_to_project(folder_name):
    """按文件夹名称自动匹配当前工程的单元工程。
    返回 (匹配到的项目, 候选名称列表)。"""
    folder = str(folder_name or "").strip()
    folder_key = folder_core_name(folder)
    if not folder or not folder_key:
        return None, []
    best = None
    best_score = 0
    candidates = []
    for project in manager.list_projects():
        code = str(project.get("project_code") or "").strip()
        display_code = str(project.get("display_project_code") or "").strip()
        name = str(project.get("project_name") or "").strip()
        unit_name = str((project.get("source_fields") or {}).get("单元工程名称") or name or "").strip()
        for raw, base_score in ((code, 700), (display_code, 650), (unit_name, 500), (name, 450)):
            if not raw:
                continue
            key = folder_core_name(raw)
            if not key:
                continue
            score = 0
            if key == folder_key:
                score = 100000 + base_score + len(key)
            elif key and folder_key and (key in folder or folder_key in key):
                score = base_score + min(len(key), len(folder_key)) * 10
            if score > 0:
                candidates.append((raw, score))
            if score > best_score:
                best_score = score
                best = project
    candidates.sort(key=lambda item: item[1], reverse=True)
    return best, [item[0] for item in candidates[:5]]


def clean_folder_title(name):
    return re.sub(r"^\s*\d+[.、\-_]?\s*", "", str(name or "")).strip() or str(name or "").strip()


def other_folder_code(prefix, index):
    return f"{prefix}-{index:03d}" if prefix else f"QTYX-{index:03d}"


def build_other_nodes_from_folder(root: Path, parent_code=""):
    nodes = []
    if not root.exists() or not root.is_dir():
        return nodes
    children = sorted(
        [item for item in root.iterdir() if item.is_dir()],
        key=lambda item: natural_sort_key(item.name),
    )
    for index, child in enumerate(children, start=1):
        code = other_folder_code(parent_code, index)
        node = {
            "code": code,
            "name": clean_folder_title(child.name),
            "folder_name": child.name,
            "folder_path": str(child),
            "children": build_other_nodes_from_folder(child, code),
        }
        nodes.append(node)
    return nodes


def ensure_other_image_projects(nodes, path_parts=None, order_start=0):
    path_parts = path_parts or []
    order = order_start
    for node in nodes:
        order += 1
        code = str(node.get("code") or "").strip()
        name = str(node.get("name") or code).strip()
        folder_name = str(node.get("folder_name") or name).strip()
        current_path = path_parts + [folder_name]
        manager.create_project(
            code,
            name,
            source_fields={
                OTHER_IMAGE_MARKER: True,
                "工程其它影像": "是",
                "自定义编号": code,
                "文件夹名称": folder_name,
                "文件夹路径": str(node.get("folder_path") or ""),
                "层级路径": " / ".join(current_path),
            },
            project_order=order,
        )
        order = ensure_other_image_projects(node.get("children", []) or [], current_path, order)
    return order


def seed_other_images_from_folder(force=False):
    data = read_other_images()
    if data.get("nodes") and not force:
        ensure_other_image_projects(data.get("nodes") or [])
        return data
    nodes = build_other_nodes_from_folder(OTHER_IMAGES_TEMPLATE_DIR)
    if not nodes:
        return data
    data = {"nodes": nodes, "source_folder": str(OTHER_IMAGES_TEMPLATE_DIR)}
    write_other_images(data)
    ensure_other_image_projects(nodes)
    return data


PROJECT_INFO_FIELDS = [
    "project_name",
    "project_code",
    "owner",
    "contractor",
    "supervisor",
    "location",
    "start_date",
    "description",
]


def safe_engineering_project_id(value):
    text = str(value or "").strip()
    if not text:
        return DEFAULT_ENGINEERING_PROJECT_ID
    text = re.sub(r"[^A-Za-z0-9_\-.]+", "-", text)
    text = text.strip("-._")
    return text[:80] or DEFAULT_ENGINEERING_PROJECT_ID


def default_engineering_project():
    info = read_project_info()
    name = info.get("project_name") or "默认工程"
    code = info.get("project_code") or DEFAULT_ENGINEERING_PROJECT_ID
    return {
        "id": DEFAULT_ENGINEERING_PROJECT_ID,
        "project_name": name,
        "project_code": code,
        "owner": info.get("owner", ""),
        "contractor": info.get("contractor", ""),
        "supervisor": info.get("supervisor", ""),
        "location": info.get("location", ""),
        "start_date": info.get("start_date", ""),
        "description": info.get("description", ""),
        "delete_password": DELETE_SAFETY_PASSWORD,
        "created_at": "",
        "updated_at": "",
    }


def read_engineering_projects():
    default_project = default_engineering_project()
    if not ENGINEERING_PROJECTS_PATH.exists():
        return {"active_id": default_project["id"], "projects": [default_project]}
    try:
        data = json.loads(ENGINEERING_PROJECTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"active_id": default_project["id"], "projects": [default_project]}
    projects = []
    seen = set()
    for item in data.get("projects", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        project = dict(default_project)
        project.update({key: str(item.get(key) or "").strip() for key in project.keys()})
        project["id"] = safe_engineering_project_id(item.get("id") or item.get("project_code") or item.get("project_name"))
        if not project["id"] or project["id"] in seen:
            continue
        if not project.get("project_name"):
            project["project_name"] = project["id"]
        if not project.get("delete_password"):
            project["delete_password"] = DELETE_SAFETY_PASSWORD
        seen.add(project["id"])
        projects.append(project)
    if not projects:
        projects = [default_project]
    active_id = safe_engineering_project_id(data.get("active_id") if isinstance(data, dict) else "")
    if active_id not in {item["id"] for item in projects}:
        active_id = projects[0]["id"]
    return {"active_id": active_id, "projects": projects}


def write_engineering_projects(data):
    ENGINEERING_PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENGINEERING_PROJECTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    active_project = current_engineering_project(data)
    write_project_info(active_project)
    return data


def current_engineering_project(data=None):
    data = data or read_engineering_projects()
    active_id = data.get("active_id") or DEFAULT_ENGINEERING_PROJECT_ID
    for project in data.get("projects", []):
        if project.get("id") == active_id:
            return project
    return (data.get("projects") or [default_engineering_project()])[0]


def active_engineering_project_id():
    return current_engineering_project().get("id") or DEFAULT_ENGINEERING_PROJECT_ID


def project_matches_engineering(data, project_id=None):
    project_id = project_id or active_engineering_project_id()
    source_fields = data.get("source_fields", {}) if isinstance(data, dict) else {}
    stored = str(source_fields.get("工程项目ID") or data.get("engineering_project_id") or "").strip()
    stored = str(source_fields.get("工程项目ID") or stored).strip()
    return stored == project_id or (project_id == DEFAULT_ENGINEERING_PROJECT_ID and not stored)


def ensure_engineering_delete_password(value):
    expected = str(current_engineering_project().get("delete_password") or DELETE_SAFETY_PASSWORD)
    if str(value or "") != expected:
        raise ValueError("当前工程删除密码错误")


def default_project_info():
    return {field: "" for field in PROJECT_INFO_FIELDS}


def read_project_info():
    if not PROJECT_INFO_PATH.exists():
        return default_project_info()
    try:
        data = json.loads(PROJECT_INFO_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_project_info()
    info = default_project_info()
    if isinstance(data, dict):
        for field in PROJECT_INFO_FIELDS:
            info[field] = str(data.get(field) or "").strip()
    return info


def write_project_info(payload):
    info = default_project_info()
    for field in PROJECT_INFO_FIELDS:
        info[field] = str(payload.get(field) or "").strip()
    PROJECT_INFO_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROJECT_INFO_PATH.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


def walk_other_nodes(nodes):
    for node in nodes:
        yield node
        yield from walk_other_nodes(node.get("children", []) or [])


def find_other_node(nodes, code):
    code = str(code or "").strip()
    for node in walk_other_nodes(nodes):
        if str(node.get("code") or "").strip() == code:
            return node
    return None


def remove_other_node(nodes, code):
    code = str(code or "").strip()
    for index, node in enumerate(list(nodes)):
        if str(node.get("code") or "").strip() == code:
            removed = nodes.pop(index)
            return removed
        removed = remove_other_node(node.get("children", []) or [], code)
        if removed:
            return removed
    return None


def other_node_codes(node):
    codes = []
    code = str((node or {}).get("code") or "").strip()
    if code:
        codes.append(code)
    for child in (node or {}).get("children", []) or []:
        codes.extend(other_node_codes(child))
    return codes


def delete_other_image_node(code):
    data = read_other_images()
    nodes = data.setdefault("nodes", [])
    removed = remove_other_node(nodes, code)
    if not removed:
        raise ValueError("其它影像目录不存在")

    removed_codes = other_node_codes(removed)
    for project_code in removed_codes:
        project_dir = manager._project_dir(project_code).resolve()
        root = manager.root.resolve()
        if root in project_dir.parents and project_dir.exists():
            shutil.rmtree(project_dir)

    write_other_images(data)
    manager.invalidate_projects_cache()
    return {"removed": removed, "removed_codes": removed_codes}


def enrich_other_nodes(nodes, project_map):
    enriched = []
    for node in nodes:
        code = str(node.get("code") or "").strip()
        children = enrich_other_nodes(node.get("children", []) or [], project_map)
        project = project_map.get(code, {})
        own_count = int(project.get("photo_count") or 0)
        child_count = sum(int(child.get("photo_count_total") or 0) for child in children)
        enriched.append({
            "code": code,
            "name": str(node.get("name") or code or "未命名").strip(),
            "children": children,
            "photo_count": own_count,
            "photo_count_total": own_count + child_count,
            "latest_upload": project.get("latest_upload", ""),
        })
    return enriched


def other_images_tree():
    data = seed_other_images_from_folder()
    projects = manager.list_projects(include_other=True)
    project_map = {
        project["project_code"]: project
        for project in projects
        if project.get("is_other_image")
    }
    nodes = enrich_other_nodes(data.get("nodes", []), project_map)
    return {
        "nodes": nodes,
        "photo_count": sum(int(node.get("photo_count_total") or 0) for node in nodes),
    }


def create_other_image_node(payload):
    raw_code = str(payload.get("code") or "").strip()
    if not raw_code:
        raise ValueError("请输入其它影像编号")
    code = manager._safe_code(raw_code)
    name = str(payload.get("name") or code).strip()
    parent_code = str(payload.get("parent_code") or "").strip()
    if not name:
        raise ValueError("请输入其它影像名称")

    data = read_other_images()
    nodes = data.setdefault("nodes", [])
    if find_other_node(nodes, code):
        raise ValueError("其它影像编号已存在")

    metadata_path = manager._metadata_path(code)
    if metadata_path.exists():
        existing = manager.get_project(code)
        if not (existing.get("source_fields") or {}).get(OTHER_IMAGE_MARKER):
            raise ValueError("该编号已被项目划分使用，请换一个编号")

    target_list = nodes
    if parent_code:
        parent = find_other_node(nodes, parent_code)
        if not parent:
            raise ValueError("上级其它影像不存在")
        target_list = parent.setdefault("children", [])

    node = {"code": code, "name": name, "children": []}
    target_list.append(node)
    write_other_images(data)
    manager.create_project(
        code,
        name,
        source_fields={
            OTHER_IMAGE_MARKER: True,
            "工程其它影像": "是",
            "上级编号": parent_code,
            "自定义编号": code,
        },
    )
    return node


@app.route("/")
def index():
    return render_template("index.html", default_project_table=str(DEFAULT_PROJECT_TABLE))


@app.route("/poster")
def poster_page():
    return render_template("poster.html")


@app.route("/license")
def license_page():
    return render_template("license.html", license_status=app_license_status())


@app.route("/api/license/status")
def api_license_status():
    return jsonify({"ok": True, "license": app_license_status()})


@app.route("/api/license/activate", methods=["POST"])
def api_license_activate():
    payload = request.get_json(silent=True) or request.form
    code = str(payload.get("license_code", "")).strip()
    try:
        licensing.write_installed_license(code)
        return jsonify({"ok": True, "license": app_license_status()})
    except Exception as exc:
        return json_error(str(exc), 403)


@app.route("/api/cloud/status")
def api_cloud_status():
    return jsonify(cloud_client.status())


@app.route("/api/cloud/login", methods=["POST"])
def api_cloud_login():
    payload = request.get_json(silent=True) or {}
    result = cloud_client.login(
        str(payload.get("username") or "").strip(),
        str(payload.get("password") or ""),
    )
    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "登录失败")}), 400
    return jsonify(result)


@app.route("/api/cloud/send-code", methods=["POST"])
def api_cloud_send_code():
    payload = request.get_json(silent=True) or {}
    result = cloud_client.send_code(str(payload.get("account") or "").strip())
    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "发送失败")}), 400
    return jsonify(result)


@app.route("/api/cloud/register", methods=["POST"])
def api_cloud_register():
    payload = request.get_json(silent=True) or {}
    result = cloud_client.register(
        str(payload.get("username") or "").strip(),
        str(payload.get("password") or ""),
        str(payload.get("code") or "").strip(),
        str(payload.get("invite_code") or "").strip(),
        str(payload.get("email") or "").strip(),
    )
    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "注册失败")}), 400
    return jsonify(result)


@app.route("/api/cloud/forgot-password", methods=["POST"])
def api_cloud_forgot_password():
    payload = request.get_json(silent=True) or {}
    result = cloud_client.forgot_password(str(payload.get("account") or "").strip())
    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "发送失败")}), 400
    return jsonify(result)


@app.route("/api/cloud/reset-password", methods=["POST"])
def api_cloud_reset_password():
    payload = request.get_json(silent=True) or {}
    result = cloud_client.reset_password(
        str(payload.get("account") or "").strip(),
        str(payload.get("code") or "").strip(),
        str(payload.get("new_password") or ""),
    )
    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "重置失败")}), 400
    return jsonify(result)


@app.route("/api/cloud/invite-status")
def api_cloud_invite_status():
    return jsonify(cloud_client.invite_status())


@app.route("/api/cloud/check-update")
def api_cloud_check_update():
    return jsonify(cloud_client.check_update())


@app.route("/api/cloud/download-update")
def api_cloud_download_update():
    """跳转到服务器下载最新安装包。"""
    import urllib.parse

    result = cloud_client.check_update()
    url = result.get("download_url") or ""
    if not url or not result.get("has_update"):
        return jsonify({"ok": False, "error": "当前已是最新版本"}), 400
    return redirect(url)


@app.route("/api/cloud/logout", methods=["POST"])
def api_cloud_logout():
    return jsonify(cloud_client.logout())


@app.route("/api/cloud/sync", methods=["POST"])
def api_cloud_sync():
    result = cloud_client.sync()
    if not result.get("ok"):
        return jsonify(result), 403 if result.get("offline_expired") else 400
    return jsonify(result)


@app.route("/api/numbering-rules", methods=["GET"])
def api_numbering_rules():
    return jsonify({"ok": True, "rules": read_numbering_rules()})


@app.route("/api/numbering-rules", methods=["POST"])
def api_save_numbering_rules():
    payload = request.get_json(silent=True) or {}
    try:
        rules = write_numbering_rules(payload.get("rules") or payload)
        return jsonify({"ok": True, "rules": rules})
    except ValueError as exc:
        return json_error(str(exc), 400)


@app.route("/api/engineering-settings", methods=["GET"])
def api_engineering_settings():
    return jsonify({"ok": True, "settings": read_engineering_settings(), "standard_rules": standard_unit_rules()[:80]})


@app.route("/api/engineering-settings", methods=["POST"])
def api_save_engineering_settings():
    user, error = login_required_json()
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    try:
        settings = write_engineering_settings(payload.get("settings") or payload)
        return jsonify({"ok": True, "settings": settings})
    except ValueError as exc:
        return json_error(str(exc), 400)


@app.route("/api/share-points", methods=["GET"])
def api_share_points():
    return jsonify({"ok": True, "share": share_points_status()})


@app.route("/api/share-points", methods=["POST"])
def api_add_share_points():
    try:
        payload = request.get_json(silent=True) or request.form
        share = add_share_points(payload.get("target", ""), payload.get("note", ""))
        return jsonify({"ok": True, "share": share})
    except Exception as exc:
        return json_error(str(exc), 400)


@app.route("/setup")
def setup_page():
    return render_template("setup.html")


@app.route("/api/setup/status")
def api_setup_status():
    return jsonify({"ok": True, "setup": setup_status()})


@app.route("/api/setup/auto-config", methods=["POST"])
def api_setup_auto_config():
    if not is_local_setup_request():
        return json_error("一键配置只能在服务器电脑本机运行，请在本机打开配置页。", 403)
    port = runtime_port()
    payload = request.get_json(silent=True) or {}
    if payload.get("port"):
        try:
            port = int(payload.get("port"))
        except (TypeError, ValueError):
            return json_error("端口号必须是数字")
    if not 1024 <= port <= 65535:
        return json_error("端口号需要在 1024-65535 之间")
    write_portable_setup(port)
    return jsonify({
        "ok": True,
        "setup": setup_status(),
        "message": "已生成便携启动配置。以后把整个文件夹发给别人，运行 start_album.bat 即可打开配置页。",
    })


@app.route("/api/dashboard")
def api_dashboard():
    return jsonify({"ok": True, "dashboard": manager.dashboard()})


def _public_project(project):
    """下发给前端的工程信息不包含删除密码（校验仍在服务端执行）。"""
    if not isinstance(project, dict):
        return project
    out = dict(project)
    out.pop("delete_password", None)
    return out


@app.route("/api/project-info", methods=["GET"])
def api_project_info():
    data = read_engineering_projects()
    return jsonify({
        "ok": True,
        "project_info": _public_project(current_engineering_project(data)),
        "engineering_projects": [_public_project(p) for p in data.get("projects", [])],
        "active_engineering_project_id": data.get("active_id"),
    })


@app.route("/api/project-info", methods=["POST"])
def api_save_project_info():
    user, error = login_required_json()
    if error:
        return error
    payload = request.get_json(silent=True) or request.form
    try:
        data = read_engineering_projects()
        project_id = safe_engineering_project_id(payload.get("id") or payload.get("project_code") or payload.get("project_name"))
        now = now_text()
        existing_pwd = next(
            (item.get("delete_password") for item in data.get("projects", []) if item.get("id") == project_id),
            None,
        )
        new_pwd = str(payload.get("delete_password") or "").strip()
        project = {
            "id": project_id,
            "project_name": str(payload.get("project_name") or project_id).strip(),
            "project_code": str(payload.get("project_code") or project_id).strip(),
            "owner": str(payload.get("owner") or "").strip(),
            "contractor": str(payload.get("contractor") or "").strip(),
            "supervisor": str(payload.get("supervisor") or "").strip(),
            "location": str(payload.get("location") or "").strip(),
            "start_date": str(payload.get("start_date") or "").strip(),
            "description": str(payload.get("description") or "").strip(),
            "delete_password": new_pwd or existing_pwd or DELETE_SAFETY_PASSWORD,
            "created_at": now,
            "updated_at": now,
        }
        replaced = False
        for index, item in enumerate(data.get("projects", [])):
            if item.get("id") == project_id:
                project["created_at"] = item.get("created_at") or now
                data["projects"][index] = project
                replaced = True
                break
        if not replaced:
            data.setdefault("projects", []).append(project)
        data["active_id"] = project_id
        write_engineering_projects(data)
        return jsonify({
            "ok": True,
            "project_info": _public_project(project),
            "engineering_projects": [_public_project(p) for p in data.get("projects", [])],
            "active_engineering_project_id": data.get("active_id"),
        })
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/engineering-projects/active", methods=["POST"])
def api_set_active_engineering_project():
    user, error = login_required_json()
    if error:
        return error
    payload = request.get_json(silent=True) or request.form
    project_id = safe_engineering_project_id(payload.get("id"))
    data = read_engineering_projects()
    if project_id not in {item.get("id") for item in data.get("projects", [])}:
        return json_error("工程项目不存在", 404)
    data["active_id"] = project_id
    write_engineering_projects(data)
    return jsonify({
        "ok": True,
        "project_info": current_engineering_project(data),
        "engineering_projects": data.get("projects", []),
        "active_engineering_project_id": data.get("active_id"),
    })


@app.route("/api/engineering-projects/<path:project_id>", methods=["DELETE"])
def api_delete_engineering_project(project_id):
    user, error = login_required_json()
    if error:
        return error
    payload = request.get_json(silent=True) or request.form
    data = read_engineering_projects()
    target_id = safe_engineering_project_id(project_id)
    target = next((item for item in data.get("projects", []) if item.get("id") == target_id), None)
    if not target:
        return json_error("工程项目不存在", 404)
    if str(payload.get("delete_password", "")) != str(target.get("delete_password") or DELETE_SAFETY_PASSWORD):
        return json_error("当前工程删除密码错误", 403)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ALBUMS_DIR / f"_deleted_engineering_project_{target_id}_{stamp}"
    moved = 0
    for project_dir in list(ALBUMS_DIR.iterdir()):
        if not project_dir.is_dir() or project_dir.name.startswith("_"):
            continue
        try:
            metadata = manager._read_metadata(project_dir.name)
        except Exception:
            continue
        if project_matches_engineering(metadata, target_id):
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(project_dir), str(backup_dir / project_dir.name))
            moved += 1
    data["projects"] = [item for item in data.get("projects", []) if item.get("id") != target_id]
    if not data["projects"]:
        data["projects"] = [default_engineering_project()]
    if data.get("active_id") == target_id:
        data["active_id"] = data["projects"][0]["id"]
    write_engineering_projects(data)
    manager.invalidate_projects_cache()
    return jsonify({
        "ok": True,
        "deleted": moved,
        "backup": str(backup_dir) if moved else "",
        "project_info": current_engineering_project(data),
        "engineering_projects": data.get("projects", []),
        "active_engineering_project_id": data.get("active_id"),
    })


@app.route("/api/projects", methods=["GET"])
def api_projects():
    query = request.args.get("q", "")
    projects = manager.list_projects(query)
    if str(request.args.get("slim") or "").lower() in {"1", "true", "yes"}:
        hierarchy_keys = {
            "合同工程名称",
            "单位工程名称",
            "单位工程编码",
            "单位工程名称及编码",
            "单位工程",
            "分部工程名称",
            "分部工程编码",
            "分项工程名称",
            "分项工程编码",
            "分部工程名称及编码",
            "分部工程",
            "分项工程",
            "单元工程名称",
            "单元名称",
            "单元工程编码",
            "单元工程编号",
            "单元编码",
            "项目划分顺序",
            "导入顺序",
            "import_order",
        }
        slim_projects = []
        for project in projects:
            source_fields = project.get("source_fields") or {}
            slim_projects.append({
                "project_code": project.get("project_code", ""),
                "display_project_code": project.get("display_project_code", ""),
                "project_name": project.get("project_name", ""),
                "photo_count": project.get("photo_count", 0),
                "construction_photo_count": project.get("construction_photo_count", 0),
                "supervision_photo_count": project.get("supervision_photo_count", 0),
                "latest_upload": project.get("latest_upload", ""),
                "standard_unit_name": project.get("standard_unit_name", ""),
                "division_type": project.get("division_type", "unit"),
                "processes": project.get("processes", []),
                "project_order": project.get("project_order"),
                "is_other_image": project.get("is_other_image", False),
                "source_fields": {
                    key: value
                    for key, value in source_fields.items()
                    if key in hierarchy_keys
                },
            })
        projects = slim_projects
    return jsonify({"ok": True, "projects": projects})


@app.route("/api/projects", methods=["POST"])
def api_create_project():
    data = request.get_json(silent=True) or request.form
    project_code = data.get("project_code") or data.get("code") or data.get("name")
    project_name = data.get("project_name") or data.get("name") or project_code
    if not project_code:
        return json_error("请输入项目编码或名称")
    try:
        project = manager.create_project(project_code, project_name, data.get("keywords", ""))
        return jsonify({"ok": True, "project": project})
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/other-images/tree")
def api_other_images_tree():
    return jsonify({"ok": True, "tree": other_images_tree()})


@app.route("/api/other-images/nodes", methods=["POST"])
def api_create_other_image_node():
    user, error = login_required_json()
    if error:
        return error
    payload = request.get_json(silent=True) or request.form
    try:
        node = create_other_image_node(payload)
        return jsonify({
            "ok": True,
            "node": node,
            "tree": other_images_tree(),
            "projects": manager.list_projects(),
        })
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/other-images/nodes/<path:code>", methods=["DELETE"])
def api_delete_other_image_node(code):
    user, error = login_required_json()
    if error:
        return error
    try:
        result = delete_other_image_node(code)
        return jsonify({
            "ok": True,
            "result": result,
            "tree": other_images_tree(),
            "projects": manager.list_projects(),
        })
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/import-projects", methods=["POST"])
def api_import_projects():
    temp_path = None
    try:
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return json_error("请选择要导入的项目划分表文件")

        ext = Path(uploaded.filename).suffix.lower()
        if ext not in PROJECT_IMPORT_EXTENSIONS:
            return json_error("项目划分表只支持 .xlsx/.xlsm/.csv 文件")

        if ext in EXCEL_EXTENSIONS and load_workbook is None:
            return json_error("缺少 openpyxl，请先运行：pip install -r requirements.txt", 500)

        safe_name = secure_filename(uploaded.filename)
        stem = Path(safe_name).stem or "projects"
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        temp_ext = ext
        head = uploaded.stream.read(4)
        uploaded.stream.seek(0)
        if ext == ".csv" and head.startswith(b"PK\x03\x04"):
            if load_workbook is None:
                return json_error("缺少 openpyxl，请先运行：pip install -r requirements.txt", 500)
            temp_ext = ".xlsx"
        temp_path = ALBUMS_DIR / f"_import_{stamp}_{stem}{temp_ext}"
        uploaded.save(temp_path)

        if temp_ext == ".csv":
            result = manager.import_projects_from_text(read_text_with_fallback(temp_path))
        else:
            result = manager.import_projects_from_xlsx(temp_path)
        return jsonify({
            "ok": True,
            "message": "项目划分导入完成",
            "result": result,
            "projects": manager.list_projects(),
        })
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        return json_error(str(exc))
    except Exception as exc:
        return json_error(f"Excel 解析失败：{exc}", 500)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


@app.route("/api/project-template.csv")
def api_project_template():
    template_csv = BASE_DIR / "assets" / "project_template.csv"
    if template_csv.exists():
        return send_file(
            template_csv,
            mimetype="text/csv; charset=utf-8",
            as_attachment=True,
            download_name="项目划分导入模板.csv",
        )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(PROJECT_TEMPLATE_HEADERS)
    writer.writerows(PROJECT_TEMPLATE_ROWS)
    memory = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(
        memory,
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name="项目划分导入模板.csv",
    )


@app.route("/api/project-template.xlsx")
def api_project_template_xlsx():
    if load_workbook is None:
        return json_error("缺少 openpyxl，请先运行：pip install -r requirements.txt", 500)
    if PROJECT_TEMPLATE_XLSX_PATH.exists():
        return send_file(
            PROJECT_TEMPLATE_XLSX_PATH,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="项目划分导入模板.xlsx",
        )
    try:
        from openpyxl import Workbook
    except Exception as exc:
        return json_error(f"Excel 模板生成失败：{exc}", 500)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "项目划分"
    sheet.append(PROJECT_TEMPLATE_HEADERS)
    for row in PROJECT_TEMPLATE_ROWS:
        sheet.append(row)
    for column in sheet.columns:
        max_len = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[column[0].column_letter].width = min(max(max_len + 2, 12), 32)
    memory = io.BytesIO()
    workbook.save(memory)
    memory.seek(0)
    return send_file(
        memory,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="项目划分导入模板.xlsx",
    )


@app.route("/api/import-projects-text", methods=["POST"])
def api_import_projects_text():
    try:
        _user, error = login_required_json()
        if error:
            return error
        payload = request.get_json(silent=True) or request.form
        result = manager.import_projects_from_text(payload.get("text", ""))
        return jsonify({
            "ok": True,
            "message": "粘贴项目划分导入完成",
            **result,
            "projects": manager.list_projects(),
        })
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/clear-projects", methods=["POST"])
def api_clear_projects():
    try:
        _user, error = login_required_json()
        if error:
            return error
        payload = request.get_json(silent=True) or request.form
        ensure_engineering_delete_password(payload.get("safety_password", ""))
        result = manager.clear_project_division()
        return jsonify({
            "ok": True,
            "message": "当前项目划分已清空",
            **result,
            "projects": manager.list_projects(),
        })
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/classify", methods=["POST"])
def api_classify():
    data = request.get_json(silent=True) or request.form
    try:
        return jsonify({"ok": True, **manager.classify(data.get("prompt", ""))})
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/upload/<path:project_code>", methods=["POST"])
def api_upload(project_code):
    user, error = login_required_json()
    if error:
        return error
    if not manager._metadata_path(project_code).exists():
        return json_error("项目不存在，请先创建或导入项目")
    files = request.files.getlist("files")
    if not files:
        single = request.files.get("file")
        files = [single] if single else []
    if not files:
        return json_error("请选择要上传的 JPG/PNG 图片")
    try:
        files = validate_upload_files(files)
        photo_date = str(request.form.get("photo_date") or "").strip()
        title = str(request.form.get("title") or "").strip()
        # 文件名自动识别：题名/日期未填时，从文件名解析；解析不到日期再读 EXIF
        for file_storage in files:
            parsed_title, parsed_date = parse_photo_name_parts(file_storage.filename)
            if not title and parsed_title:
                title = parsed_title
            if not photo_date:
                if parsed_date:
                    photo_date = parsed_date
                else:
                    try:
                        file_storage.stream.seek(0)
                        photo_date = photo_exif_date(file_storage.stream)
                        file_storage.stream.seek(0)
                    except Exception:
                        pass
        limit_response = trial_upload_limit_response(len(files))
        if limit_response:
            return limit_response
        per_file_meta, title, photo_date = _enrich_watermark_metadata(
            files,
            title,
            photo_date,
            read_engineering_settings().get("watermark_ocr_enabled", False),
            form_title=str(request.form.get("title") or "").strip(),
            form_date=str(request.form.get("photo_date") or "").strip(),
        )
        if not photo_date:
            return json_error("请填写照片日期（文件名、EXIF 或水印中无日期）", 400)
        added = manager.add_photos(
            project_code,
            files,
            request.form.get("category", "construction"),
            title,
            photo_date,
            request.form.get("photographer", ""),
            request.form.get("description", ""),
            uploaded_by=user["username"],
            orientation=request.form.get("orientation", "landscape"),
            process_name=request.form.get("process_name", ""),
            process_code=request.form.get("process_code", ""),
            per_file_meta=per_file_meta or None,
        )
        sync_cloud_preview_async()  # 上传后自动同步缩略图到云预览
        return jsonify({"ok": True, "added": added, "photos": manager.get_photos(project_code)})
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/upload-folder", methods=["POST"])
def api_upload_folder():
    user, error = login_required_json()
    if error:
        return error
    files = request.files.getlist("files")
    if not files:
        return json_error("请选择文件夹中的照片")
    try:
        files = validate_upload_files(files)
    except ValueError as exc:
        return json_error(str(exc), 400)
    folder_name = str(request.form.get("folder_name") or "").strip()
    unit_code = str(request.form.get("unit_code") or "").strip()
    category = manager._normalize_category(request.form.get("category", "construction"))
    try:
        project = None
        if unit_code:
            try:
                project = manager.get_project(unit_code)
            except FileNotFoundError:
                return json_error("指定的单元不存在，请先导入项目划分。", 400)
        else:
            project, candidates = match_folder_to_project(folder_name)
            if not project:
                hint = "、".join(candidates) if candidates else "无"
                return json_error(
                    f"文件夹“{folder_name}”未匹配到单元（相近单元：{hint}）。"
                    "请确认已切换到对应工程并导入项目划分，或文件夹名包含单元编码/单元名称。",
                    400,
                )
        files = sorted(files, key=lambda item: natural_sort_key(item.filename or ""))
        enabled_ocr = read_engineering_settings().get("watermark_ocr_enabled", False)
        added = []
        for file_storage in files:
            title, photo_date = parse_photo_name_parts(file_storage.filename)
            if not photo_date:
                try:
                    file_storage.stream.seek(0)
                    photo_date = photo_exif_date(file_storage.stream)
                    file_storage.stream.seek(0)
                except Exception:
                    pass
            per_file_meta = {}
            if enabled_ocr:
                meta = _watermark_meta_for_upload(file_storage)
                if meta:
                    if not title and meta.get("title"):
                        title = meta["title"]
                    if not photo_date and meta.get("photo_date"):
                        photo_date = meta["photo_date"]
                    per_file_meta[file_storage.filename] = meta
            added.extend(manager.add_photos(
                project["project_code"],
                [file_storage],
                category=category,
                title=title,
                photo_date=photo_date or "",
                uploaded_by=user["username"],
                orientation="landscape",
                per_file_meta=per_file_meta or None,
            ))
        return jsonify({
            "ok": True,
            "added": added,
            "project_code": project.get("project_code"),
            "project_name": project.get("project_name"),
            "photos": manager.get_photos(project["project_code"]),
        })
    except Exception as exc:
        return json_error(str(exc), 500)


@app.route("/api/upload-auto-match", methods=["POST"])
def api_upload_auto_match():
    user, error = login_required_json()
    if error:
        return error
    files = request.files.getlist("files")
    if not files:
        single = request.files.get("file")
        files = [single] if single else []
    if not files:
        return json_error("请选择要上传的 JPG/PNG 图片")
    try:
        files = validate_upload_files(files)
        photo_date = str(request.form.get("photo_date") or "").strip()
        if not photo_date:
            return json_error("请填写照片日期", 400)
        matched = {}
        unmatched = []
        for file_storage in files:
            project = match_project_by_filename(file_storage.filename)
            if not project:
                unmatched.append(file_storage.filename)
                continue
            code = project.get("project_code")
            matched.setdefault(code, {"project": project, "files": []})["files"].append(file_storage)

        matched_count = sum(len(item["files"]) for item in matched.values())
        if not matched_count:
            return json_error("没有照片匹配到单元。请把单元编码或单元名称放到照片文件名中。")
        limit_response = trial_upload_limit_response(matched_count)
        if limit_response:
            return limit_response

        groups = []
        total_added = 0
        for code, item in matched.items():
            for file_storage in item["files"]:
                # 逐张照片从文件名解析题名/日期（表单没填时）
                f_title, f_date = parse_photo_name_parts(file_storage.filename)
                per_date = photo_date or f_date
                if not per_date:
                    try:
                        file_storage.stream.seek(0)
                        per_date = photo_exif_date(file_storage.stream)
                        file_storage.stream.seek(0)
                    except Exception:
                        pass
                per_file_meta = {}
                if read_engineering_settings().get("watermark_ocr_enabled", False):
                    meta = _watermark_meta_for_upload(file_storage)
                    if meta:
                        if not f_title and meta.get("title"):
                            f_title = meta["title"]
                        if not per_date and meta.get("photo_date"):
                            per_date = meta["photo_date"]
                        per_file_meta[file_storage.filename] = meta
                added = manager.add_photos(
                    code,
                    [file_storage],
                    request.form.get("category", "construction"),
                    f_title,
                    per_date or "",
                    request.form.get("photographer", ""),
                    request.form.get("description", ""),
                    uploaded_by=user["username"],
                    orientation=request.form.get("orientation", "landscape"),
                    process_name=request.form.get("process_name", ""),
                    process_code=request.form.get("process_code", ""),
                    per_file_meta=per_file_meta or None,
                )
                total_added += len(added)
            groups.append({
                "project_code": code,
                "project_name": item["project"].get("project_name") or code,
                "count": len(item["files"]),
                "files": [file_storage.filename for file_storage in item["files"]],
            })
        return jsonify({
            "ok": True,
            "added_count": total_added,
            "project_count": len(groups),
            "groups": groups,
            "unmatched": unmatched,
        })
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/photos/<path:project_code>")
def api_photos(project_code):
    try:
        project = manager.get_project(project_code)
        return jsonify({"ok": True, "project": project, "photos": manager.get_photos(project_code)})
    except Exception as exc:
        return json_error(str(exc), 404)


@app.route("/api/photos/<path:project_code>/<photo_id>", methods=["PATCH"])
def api_update_photo(project_code, photo_id):
    user, error = login_required_json()
    if error:
        return error
    data = request.get_json(silent=True) or request.form
    try:
        photo_date = str(data.get("photo_date") or "").strip()
        if not photo_date:
            return json_error("请填写照片日期", 400)
        photo = manager.update_photo(
            project_code,
            photo_id,
            title=data.get("title", ""),
            photo_date=photo_date,
            photographer=data.get("photographer", ""),
            description=data.get("description", ""),
            process_name=data.get("process_name", ""),
            process_code=data.get("process_code", ""),
            orientation=data.get("orientation", "landscape"),
            rotation=data.get("rotation", 0),
        )
        return jsonify({"ok": True, "photo": photo, "photos": manager.get_photos(project_code)})
    except Exception as exc:
        return json_error(str(exc), 404)


@app.route("/api/photos/<path:project_code>/renumber", methods=["POST"])
def api_renumber_photos(project_code):
    user, error = login_required_json()
    if error:
        return error
    try:
        with manager._project_write_lock(project_code):
            data = manager.get_project(project_code)
            payload = request.get_json(silent=True) or request.form
            category = str(payload.get("category") or "").strip()
            categories = [manager._normalize_category(category)] if category else list(PHOTO_CATEGORIES)
            for item in categories:
                manager._renumber_category(project_code, data, item)
            manager._write_metadata(data["project_code"], data)
        return jsonify({"ok": True, "photos": manager.get_photos(project_code)})
    except Exception as exc:
        return json_error(str(exc), 404)


@app.route("/api/photos/<path:project_code>/auto-sort-piles", methods=["POST"])
def api_auto_sort_piles(project_code):
    user, error = login_required_json()
    if error:
        return error
    try:
        manager.auto_sort_piles(project_code)
        photos = manager.get_photos(project_code)
        unmatched = [
            {
                "id": str(p.get("id") or ""),
                "title": str(p.get("title") or p.get("original_name") or p.get("filename") or ""),
            }
            for p in photos
            if photo_pile_number(p) is None
        ]
        return jsonify({"ok": True, "photos": photos, "unmatched": unmatched})
    except Exception as exc:
        return json_error(str(exc), 400)


@app.route("/api/auto-sort-piles-all", methods=["POST"])
def api_auto_sort_piles_all():
    """刷新时调用：全部灌注桩单元按桩号连体+施工完成时间自动归位并重新编号。"""
    user, error = login_required_json()
    if error:
        return error
    try:
        projects = manager.list_projects()
        sorted_units = 0
        photo_count = 0
        unmatched = {}
        for project in projects:
            code = project.get("project_code")
            if not code:
                continue
            with manager._project_write_lock(code):
                data = manager.get_project(code)
                if not is_pile_unit(data):
                    continue
                manager._auto_sort_piles_locked(code, data)
            sorted_units += 1
            photo_count += len(data.get("photos") or [])
            bad = [
                str(p.get("title") or p.get("id") or "")
                for p in data.get("photos", [])
                if photo_pile_number(p) is None
            ]
            if bad:
                unmatched[str(code)] = bad
        manager.invalidate_projects_cache()
        return jsonify({
            "ok": True,
            "sorted_units": sorted_units,
            "photo_count": photo_count,
            "unmatched": unmatched,
        })
    except Exception as exc:
        return json_error(str(exc), 500)


@app.route("/api/renumber-all", methods=["POST"])
def api_renumber_all():
    user, error = login_required_json()
    if error:
        return error
    try:
        projects = manager.list_projects()
        renumbered = 0
        for project in projects:
            code = project.get("project_code")
            if not code:
                continue
            with manager._project_write_lock(code):
                data = manager.get_project(code)
                if is_pile_unit(data):
                    # 灌注桩单元：先按桩号连体+施工完成时间排序，再编号（整体重排一次完成）
                    manager._auto_sort_piles_locked(code, data)
                else:
                    for category in PHOTO_CATEGORIES:
                        manager._renumber_category(code, data, category)
                manager._write_metadata(code, data)
                renumbered += len(data.get("photos") or [])
        manager.invalidate_projects_cache()
        return jsonify({
            "ok": True,
            "renumbered": renumbered,
            "project_count": len(projects),
            "projects": manager.list_projects(),
        })
    except Exception as exc:
        return json_error(str(exc), 500)


@app.route("/api/photos/<path:project_code>/copy-construction-to-supervision", methods=["POST"])
def api_copy_construction_to_supervision(project_code):
    user, error = login_required_json()
    if error:
        return error
    payload = request.get_json(silent=True) or request.form
    try:
        added = manager.copy_construction_to_supervision(
            project_code,
            process_name=payload.get("process_name", ""),
            process_code=payload.get("process_code", ""),
        )
        return jsonify({"ok": True, "added": added, "photos": manager.get_photos(project_code)})
    except Exception as exc:
        return json_error(str(exc), 400)


@app.route("/api/photos/<path:project_code>/reorder", methods=["POST"])
def api_reorder_photo(project_code):
    user, error = login_required_json()
    if error:
        return error
    payload = request.get_json(silent=True) or request.form
    try:
        manager.reorder_photo(
            project_code,
            payload.get("photo_id", ""),
            direction=payload.get("direction", "up"),
            category=payload.get("category", ""),
        )
        return jsonify({"ok": True, "photos": manager.get_photos(project_code)})
    except Exception as exc:
        return json_error(str(exc), 404)


@app.route("/api/photos/<path:project_code>/reorder-list", methods=["POST"])
def api_reorder_photos(project_code):
    user, error = login_required_json()
    if error:
        return error
    payload = request.get_json(silent=True) or request.form
    try:
        ordered_ids = payload.get("ordered_ids", [])
        if isinstance(ordered_ids, str):
            ordered_ids = [item.strip() for item in ordered_ids.split(",") if item.strip()]
        manager.reorder_photos(project_code, ordered_ids, category=payload.get("category", ""))
        return jsonify({"ok": True, "photos": manager.get_photos(project_code)})
    except Exception as exc:
        return json_error(str(exc), 404)


def _safe_media_name(filename):
    """取文件名基名并拒绝路径分隔符，保留中文等非 ASCII 字符。

    secure_filename 会把中文全变成下划线，导致中文编号照片 404，
    这里只做防路径遍历的最小处理（send_from_directory 内部还会再校验一次）。
    """
    name = Path(str(filename or "")).name
    if name in {"", ".", ".."} or "/" in name or "\\" in name:
        return ""
    return name


@app.route("/photos/<path:project_code>/<filename>")
def photo_file(project_code, filename):
    safe_name = _safe_media_name(filename)
    if not safe_name:
        return "not found", 404
    resp = send_from_directory(manager._photos_dir(project_code), safe_name)
    if safe_name.endswith(".webp"):
        resp.mimetype = "image/webp"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/thumbs/<path:project_code>/<filename>")
def thumb_file(project_code, filename):
    safe_name = _safe_media_name(filename)
    if not safe_name:
        return "not found", 404
    if not safe_name.startswith(manager.THUMB_SUFFIX):
        safe_name = manager._thumb_filename(safe_name)
    thumb_path = manager._photos_dir(project_code) / safe_name
    if not thumb_path.exists():
        manager._ensure_thumbnail(project_code, safe_name)
    if not thumb_path.exists():
        return "not found", 404
    resp = send_from_directory(manager._photos_dir(project_code), safe_name)
    resp.mimetype = "image/webp"
    # 缩略图按文件名固定不变，可长期缓存
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


@app.route("/assets/<path:filename>")
def asset_file(filename):
    safe_name = secure_filename(filename)
    return send_from_directory(BASE_DIR / "assets", safe_name)


@app.route("/print/<category>/batch")
def print_album_category_batch(category):
    try:
        locked = expired_license_response("打印")
        if locked:
            return locked
        category = manager._normalize_category(category)
        raw_codes = request.args.get("codes", "")
        codes = [code.strip() for code in raw_codes.split(",") if code.strip()]
        mode = str(request.args.get("mode") or "print").strip().lower()
        layout = print_layout_from_request()
        page_size = print_page_size_from_request()
        if page_size == 4:
            layout = "landscape"
        if not codes:
            return "请选择要打印的单元工程", 400
        project_groups = []
        for code in codes[:300]:
            project = manager.get_project(code)
            project_photos = [
                photo for photo in manager.get_photos(code)
                if manager._normalize_category(photo.get("category")) == category
            ]
            if not project_photos:
                continue
            enriched = enrich_print_photos(project, project_photos)
            project_groups.append({
                "project_code": project.get("project_code") or code,
                "project_name": project.get("project_name") or project.get("name") or "",
                "photos": enriched,
                "pages": layout_fixed_photo_pages(enriched, layout, page_size),
            })
        project = {
            "project_code": f"{'批量导出PDF' if mode == 'pdf' else '批量打印'} {len(project_groups)} 个单元",
            "project_name": "、".join((item.get("project_name") or item.get("project_code") or "") for item in project_groups[:3])
                + (" 等" if len(project_groups) > 3 else ""),
        }
        return render_template(
            "print.html",
            project=project,
            photos=[],
            project_groups=project_groups,
            category=category,
            print_layout=layout,
            print_page_size=page_size,
            print_settings=read_engineering_settings(),
            watermark_text=watermark_text_for_user(),
            category_label=f"{PHOTO_CATEGORY_LABELS.get(category, category)}{'批量导出PDF' if mode == 'pdf' else '批量打印'}",
        )
    except Exception as exc:
        return str(exc), 404


@app.route("/print/<category>/<path:project_code>")
def print_album_category(category, project_code):
    try:
        locked = expired_license_response("打印")
        if locked:
            return locked
        category = manager._normalize_category(category)
        project = manager.get_project(project_code)
        layout = print_layout_from_request()
        page_size = print_page_size_from_request()
        if page_size == 4:
            layout = "landscape"
        photos = [
            photo for photo in manager.get_photos(project_code)
            if manager._normalize_category(photo.get("category")) == category
        ]
        selected_ids = print_photo_ids_from_request()
        if selected_ids:
            photos = [photo for photo in photos if str(photo.get("id") or "") in selected_ids]
        photos = enrich_print_photos(project, photos)
        project_groups = [{
            "project_code": project.get("project_code") or project_code,
            "project_name": project.get("project_name") or project.get("name") or "",
            "pages": layout_fixed_photo_pages(photos, layout, page_size),
        }]
        return render_template(
            "print.html",
            project=project,
            photos=photos,
            project_groups=project_groups,
            category=category,
            print_layout=layout,
            print_page_size=page_size,
            print_settings=read_engineering_settings(),
            watermark_text=watermark_text_for_user(),
            category_label=PHOTO_CATEGORY_LABELS.get(category, category),
        )
    except Exception as exc:
        return str(exc), 404


@app.route("/print/<path:project_code>")
def print_album(project_code):
    try:
        locked = expired_license_response("打印")
        if locked:
            return locked
        project = manager.get_project(project_code)
        layout = print_layout_from_request()
        page_size = print_page_size_from_request()
        if page_size == 4:
            layout = "landscape"
        photos = manager.get_photos(project_code)
        selected_ids = print_photo_ids_from_request()
        if selected_ids:
            photos = [photo for photo in photos if str(photo.get("id") or "") in selected_ids]
        photos = enrich_print_photos(project, photos)
        project_groups = [{
            "project_code": project.get("project_code") or project_code,
            "project_name": project.get("project_name") or project.get("name") or "",
            "pages": layout_fixed_photo_pages(photos, layout, page_size),
        }]
        return render_template("print.html", project=project, photos=photos, project_groups=project_groups, category="", category_label="全部影像", print_layout=layout, print_page_size=page_size, print_settings=read_engineering_settings(), watermark_text=watermark_text_for_user())
    except Exception as exc:
        return str(exc), 404


@app.route("/api/export/<path:project_code>/metadata.csv")
def export_csv_route(project_code):
    locked = expired_license_response("导出")
    if locked:
        return locked
    data = manager.export_csv(project_code)
    return send_file(
        io.BytesIO(data),
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=f"{manager._safe_code(project_code)}_metadata.csv",
    )


@app.route("/api/export/photo-statistics.xlsx")
def export_photo_statistics_route():
    locked = expired_license_response("导出统计")
    if locked:
        return locked
    try:
        memory = export_photo_statistics_xlsx(request.args.get("codes", ""))
        project = current_engineering_project()
        name = manager._safe_code(project.get("project_name") or project.get("id") or "工程")
        return send_file(
            memory,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"照片统计表_{name}_{datetime.now().strftime('%Y%m%d')}.xlsx",
        )
    except Exception as exc:
        return json_error(str(exc), 500)


@app.route("/api/export/<path:project_code>/metadata.json")
def export_json_route(project_code):
    locked = expired_license_response("导出")
    if locked:
        return locked
    data = manager.get_project(project_code)
    memory = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    return send_file(
        memory,
        mimetype="application/json",
        as_attachment=True,
        download_name=f"{manager._safe_code(project_code)}_metadata.json",
    )


@app.route("/api/export/<path:project_code>/zip")
def export_zip_route(project_code):
    locked = expired_license_response("导出")
    if locked:
        return locked
    memory = manager.export_zip(project_code)
    return send_file(
        memory,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{manager._safe_code(project_code)}_album.zip",
    )


@app.route("/api/engineering-package/export")
def export_engineering_package_route():
    locked = expired_license_response("导出工程资料包")
    if locked:
        return locked
    memory = manager.export_engineering_package()
    project = current_engineering_project()
    name = manager._safe_code(project.get("project_name") or project.get("id") or "工程资料包")
    return send_file(
        memory,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{name}_工程影像资料包.zip",
    )


@app.route("/api/engineering-package/import", methods=["POST"])
def import_engineering_package_route():
    user, error = login_required_json()
    if error:
        return error
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return json_error("请选择工程影像资料包 ZIP 文件")
    if Path(uploaded.filename).suffix.lower() != ".zip":
        return json_error("资料包只支持 .zip 文件")
    temp_path = ALBUMS_DIR / f"_package_import_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.zip"
    try:
        uploaded.save(temp_path)
        result = manager.import_engineering_package(temp_path)
        return jsonify({"ok": True, "message": "工程影像资料包导入完成", "result": result, "projects": manager.list_projects()})
    except Exception as exc:
        return json_error(str(exc))
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


@app.route("/api/delete-photo/<path:project_code>/<photo_id>", methods=["POST"])
def delete_photo(project_code, photo_id):
    try:
        _user, error = login_required_json()
        if error:
            return error
        payload = request.get_json(silent=True) or request.form
        ensure_engineering_delete_password(payload.get("safety_password", ""))
        category = manager._normalize_category(payload.get("category", "construction"))
        with manager._project_write_lock(project_code):
            data = manager.get_project(project_code)
            photos_dir = manager._photos_dir(project_code)
            kept = []
            deleted = False
            for photo in data.get("photos", []):
                photo_category = manager._normalize_category(photo.get("category"))
                if photo.get("id") == photo_id and photo_category == category:
                    target = photos_dir / photo.get("filename", "")
                    if target.exists():
                        target.unlink()
                    thumb_target = photos_dir / manager._thumb_filename(photo.get("filename", ""))
                    if thumb_target.exists():
                        thumb_target.unlink()
                    deleted = True
                else:
                    kept.append(photo)
            data["photos"] = kept
            manager._write_metadata(project_code, data)
        return jsonify({"ok": True, "deleted": deleted, "photos": manager.get_photos(project_code)})
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/delete-project/<path:project_code>", methods=["POST"])
def delete_project(project_code):
    try:
        _user, error = login_required_json()
        if error:
            return error
        payload = request.get_json(silent=True) or request.form
        ensure_engineering_delete_password(payload.get("safety_password", ""))
        manager.get_project(project_code)
        project_dir = manager._project_dir(project_code).resolve()
        root = manager.root.resolve()
        if root not in project_dir.parents:
            return json_error("项目路径无效")
        if project_dir.exists():
            shutil.rmtree(project_dir)
        manager.invalidate_projects_cache()
        return jsonify({"ok": True})
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/delete-node", methods=["POST"])
def delete_node():
    try:
        _user, error = login_required_json()
        if error:
            return error
        payload = request.get_json(silent=True) or request.form
        ensure_engineering_delete_password(payload.get("safety_password", ""))
        node_type = str(payload.get("type") or "").strip()
        name = str(payload.get("name") or "").strip()
        code = str(payload.get("code") or "").strip()
        field_map = {
            "contract": ("合同工程名称", ""),
            "unitProject": ("单位工程名称", "单位工程编码"),
            "part": ("分部工程名称", "分部工程编码"),
        }
        if node_type not in field_map:
            return json_error("删除层级不正确")
        name_field, code_field = field_map[node_type]
        combined_field = {"unitProject": "单位工程名称及编码", "part": "分部工程名称及编码", "contract": ""}.get(node_type, "")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = ALBUMS_DIR / f"_deleted_{node_type}_{stamp}"
        moved = 0

        def node_candidates(data):
            """从元数据里取该层级的名称/编码候选（兼容旧表只有“名称及编码”合并列的情况）。"""
            fields = data.get("source_fields") or {}
            names = {str(fields.get(name_field) or "").strip()}
            codes = set()
            if code_field:
                codes.add(str(fields.get(code_field) or "").strip())
            combined = str(fields.get(combined_field) or "").strip()
            if combined:
                lines = [line.strip() for line in combined.splitlines() if line.strip()]
                if lines:
                    names.add(lines[0])
                    if len(lines) >= 2:
                        codes.add(lines[1])
            return names, codes

        for project_dir in list(ALBUMS_DIR.iterdir()):
            if not project_dir.is_dir() or project_dir.name.startswith("_"):
                continue
            try:
                data = manager._read_metadata(project_dir.name)
            except Exception:
                continue
            if not project_matches_engineering(data):
                continue
            names, codes = node_candidates(data)
            same_name = name in names
            same_code = (not code_field or not code) or code in codes
            if same_name and same_code:
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(project_dir), str(backup_dir / project_dir.name))
                moved += 1
        manager.invalidate_projects_cache()
        return jsonify({"ok": True, "deleted": moved, "backup": str(backup_dir) if moved else "", "projects": manager.list_projects()})
    except Exception as exc:
        return json_error(str(exc))


@app.route("/api/delete-unit/<path:project_code>", methods=["POST"])
def delete_unit(project_code):
    """删除单个单元工程：按编码精确匹配，整个目录移入 _deleted_project_* 备份，不做任何编号重排。"""
    try:
        _user, error = login_required_json()
        if error:
            return error
        payload = request.get_json(silent=True) or request.form
        ensure_engineering_delete_password(payload.get("safety_password", ""))
        manager.get_project(project_code)
        project_dir = manager._project_dir(project_code).resolve()
        root = manager.root.resolve()
        if root not in project_dir.parents:
            return json_error("项目路径无效")
        data = manager._read_metadata(project_code)
        if not project_matches_engineering(data):
            return json_error("该项目不是工程影像项目，不能删除")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = ALBUMS_DIR / f"_deleted_project_{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(project_dir), str(backup_dir / project_dir.name))
        manager.invalidate_projects_cache()
        return jsonify({"ok": True, "deleted": 1, "backup": str(backup_dir), "projects": manager.list_projects()})
    except Exception as exc:
        return json_error(str(exc))


if __name__ == "__main__":
    run_lan_server()
