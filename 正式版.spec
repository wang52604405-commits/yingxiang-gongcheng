# -*- mode: python ; coding: utf-8 -*-
"""
正式版合并打包（onedir 模式，启动不解压）

- 启动器（工程影像管理平台.exe）与后台服务（album_server.exe）共享同一份运行时，
  安装在同一个目录，启动时直接运行，不再每次解压到临时目录；
- 安装器把整个目录装到客户电脑（见 安装脚本.iss）。
"""

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, collect_submodules

_ocr_dat = collect_all('rapidocr_onnxruntime')
_truststore_dat = collect_all('truststore')
_certifi_dat = collect_all('certifi')


def collect_onnxruntime_min():
    """只收 onnxruntime 推理核心（capi），排除 transformers 等模型优化工具（会连带拖入 scipy）。"""
    return [], collect_dynamic_libs('onnxruntime'), collect_submodules('onnxruntime.capi')


_ort_datas, _ort_binaries, _ort_hidden = collect_onnxruntime_min()

a = Analysis(
    ['desktop_launcher.py', 'server_launcher.py'],
    pathex=[],
    binaries=_ocr_dat[1] + _ort_binaries + _truststore_dat[1] + _certifi_dat[1],
    datas=[('templates', 'templates'), ('assets', 'assets')] + _ocr_dat[0] + _ort_datas + _truststore_dat[0] + _certifi_dat[0],
    hiddenimports=['openpyxl', 'xlrd', 'flask', 'werkzeug', 'pystray', 'pystray._win32', 'PIL', 'PIL.Image', 'PIL._tkinter_finder'] + _ocr_dat[2] + _ort_hidden + _truststore_dat[2] + _certifi_dat[2],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除 AI 图片识别/记忆库用的大库（图片AI识别.py、记忆库.py 是独立脚本，主程序不加载）
    excludes=['torch', 'torchvision', 'torchaudio', 'transformers', 'sentence_transformers',
              'sentencepiece', 'faiss', 'faiss_cpu', 'mem0ai', 'mem0', 'sklearn', 'scikit_learn',
              'matplotlib', 'pandas', 'seaborn'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# PyInstaller 6 会把运行时钩子（pyi_rth_*）也放进 a.scripts，
# 必须按名字选取主脚本，避免取到钩子导致程序空转退出。
_rthooks = [entry for entry in a.scripts if str(entry[0]).startswith("pyi_rth")]
_main_launcher = [entry for entry in a.scripts if entry[0] == "desktop_launcher"]
_main_server = [entry for entry in a.scripts if entry[0] == "server_launcher"]
if not _main_launcher or not _main_server:
    raise SystemExit("未找到主脚本条目: %r" % (list(a.scripts),))

exe_launcher = EXE(
    pyz,
    _rthooks + _main_launcher,
    [],
    exclude_binaries=True,
    name='工程影像管理平台',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\app_icon.ico'],
)

exe_server = EXE(
    pyz,
    _rthooks + _main_server,
    [],
    [],
    [],
    exclude_binaries=True,
    name='album_server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe_launcher,
    exe_server,
    a.binaries,
    a.datas,
    name='工程影像管理平台',
)
