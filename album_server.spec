# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, collect_submodules

_ocr_dat = collect_all('rapidocr_onnxruntime')


def collect_onnxruntime_min():
    """只收 onnxruntime 推理核心（capi），排除 transformers 等模型优化工具（会连带拖入 scipy）。"""
    return [], collect_dynamic_libs('onnxruntime'), collect_submodules('onnxruntime.capi')


_ort_datas, _ort_binaries, _ort_hidden = collect_onnxruntime_min()

a = Analysis(
    ['server_launcher.py'],
    pathex=[],
    binaries=_ocr_dat[1] + _ort_binaries,
    datas=[('templates', 'templates'), ('assets', 'assets')] + _ocr_dat[0] + _ort_datas,
    hiddenimports=['openpyxl', 'flask', 'werkzeug'] + _ocr_dat[2] + _ort_hidden,
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='album_server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
