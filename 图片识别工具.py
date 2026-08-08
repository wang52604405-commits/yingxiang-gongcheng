# -*- coding: utf-8 -*-
"""
图片识别工具（零依赖，只用 Pillow）

我怎么"识别"图片：不是用眼睛看，而是把图片变成一串"指纹"再比较——
- SHA-256：完全相同文件的指纹（改一个字节就变）；
- 感知哈希 dHash/pHash：视觉相似度的指纹（缩放、压缩、加水印后依然接近）；
- EXIF 元数据：拍摄时间、相机、方向、GPS 坐标；
- 汉明距离：两张图指纹差几位 → 换算成相似度百分比。

用法：
  python 图片识别工具.py info   图片路径              # 识别图片元信息
  python 图片识别工具.py hash   图片路径              # 生成指纹
  python 图片识别工具.py compare 图A 图B              # 两张图相似度
  python 图片识别工具.py scan   文件夹 [阈值]          # 批量找出相似/重复图片
  python 图片识别工具.py ocr    图片路径              # 识别图片中的文字（中文OCR）
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from PIL import ExifTags, Image, ImageOps


def open_image(path):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # 按 EXIF 方向摆正
    return img.convert("RGB")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dhash_bits(img, hash_size=8):
    """差分哈希：比较相邻像素亮度，抗缩放/压缩/水印。"""
    gray = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(gray.tobytes())
    bits = []
    for row in range(hash_size):
        base = row * (hash_size + 1)
        for col in range(hash_size):
            bits.append(1 if pixels[base + col] > pixels[base + col + 1] else 0)
    return bits


def ahash_bits(img, hash_size=8):
    """平均哈希：与整图平均亮度比较。"""
    gray = img.convert("L").resize((hash_size, hash_size), Image.LANCZOS)
    pixels = list(gray.tobytes())
    avg = sum(pixels) / len(pixels)
    return [1 if p > avg else 0 for p in pixels]


def bits_to_hex(bits):
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return f"{value:0{len(bits) // 4}x}"


def hamming(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


def fingerprints(path):
    img = open_image(path)
    d = dhash_bits(img)
    a = ahash_bits(img)
    return {
        "sha256": sha256_file(path),
        "dhash": bits_to_hex(d),
        "ahash": bits_to_hex(a),
        "_dhash_bits": d,
        "_ahash_bits": a,
    }


def similarity(fp_a, fp_b):
    """0~100：两张图的视觉相似度。>=90 基本可认定同一张/同一界面。"""
    d_dist = hamming(fp_a["_dhash_bits"], fp_b["_dhash_bits"])
    a_dist = hamming(fp_a["_ahash_bits"], fp_b["_ahash_bits"])
    dist = (d_dist + a_dist) / 2
    return max(0, round(100 * (1 - dist / 64), 1))


def clean_ocr_lines(result):
    """过滤可疑识别结果：大部分是问号/空白的行视为识别失败丢弃。"""
    lines = []
    for box, text, score in result:
        if not text:
            continue
        question = sum(1 for ch in text if ch in "？?")
        if question / max(1, len(text)) > 0.5:
            continue
        lines.append(text)
    return lines


def read_exif(path):
    result = {}
    try:
        img = Image.open(path)
        exif = img.getexif()
    except Exception:
        return result
    if not exif:
        return result
    for tag_id, value in exif.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        if name in {"DateTime", "DateTimeOriginal", "DateTimeDigitized",
                    "Make", "Model", "Software", "Orientation",
                    "ImageWidth", "ImageLength", "GPSInfo", "PixelXDimension",
                    "PixelYDimension", "ExifImageWidth", "ExifImageHeight"}:
            result[name] = str(value)
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo) if hasattr(ExifTags, "IFD") else None
    if gps:
        result["GPSInfo"] = str({ExifTags.GPSTAGS.get(k, k): v for k, v in gps.items()})
    return result


def cmd_info(args):
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}")
        return 1
    img = open_image(path)
    print(f"文件: {path}")
    print(f"尺寸: {img.size[0]} x {img.size[1]} 像素")
    print(f"格式: {Image.open(path).format}")
    print(f"SHA-256: {sha256_file(path)}")
    exif = read_exif(path)
    if exif:
        print("元数据:")
        for k, v in exif.items():
            print(f"  {k}: {v}")
    else:
        print("元数据: 无 EXIF（可能是截图或经处理过的图片）")
    return 0


def cmd_hash(args):
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}")
        return 1
    fp = fingerprints(path)
    print(f"文件: {path}")
    print(f"SHA-256 : {fp['sha256']}")
    print(f"dHash   : {fp['dhash']}")
    print(f"aHash   : {fp['ahash']}")
    return 0


def cmd_compare(args):
    a, b = Path(args.a), Path(args.b)
    if not a.exists() or not b.exists():
        print("文件不存在")
        return 1
    fa, fb = fingerprints(a), fingerprints(b)
    same_file = fa["sha256"] == fb["sha256"]
    score = similarity(fa, fb)
    print(f"图A: {a}")
    print(f"图B: {b}")
    print(f"文件级相同(sha256): {'是' if same_file else '否'}")
    print(f"视觉相似度: {score}%")
    if score >= 90:
        print("结论: 视觉上可认定为同一张图/同一界面")
    elif score >= 70:
        print("结论: 相似（可能是同源但经过明显修改）")
    else:
        print("结论: 不相似")
    return 0


def cmd_scan(args):
    root = Path(args.folder)
    if not root.is_dir():
        print(f"目录不存在: {root}")
        return 1
    threshold = args.threshold
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in exts
    )
    print(f"扫描到 {len(files)} 张图片，计算指纹中...")
    items = []
    for p in files:
        try:
            fp = fingerprints(p)
            items.append((p, fp))
        except Exception:
            pass
    groups = []
    used = set()
    for i, (p1, f1) in enumerate(items):
        if i in used:
            continue
        group = [p1]
        used.add(i)
        for j in range(i + 1, len(items)):
            if j in used:
                continue
            p2, f2 = items[j]
            if similarity(f1, f2) >= threshold:
                group.append(p2)
                used.add(j)
        if len(group) > 1:
            groups.append(group)
    if not groups:
        print(f"未发现相似度 >= {threshold}% 的重复图片。")
        return 0
    print(f"发现 {len(groups)} 组相似图片:")
    for g in groups:
        print(f"\n[组] 共 {len(g)} 张:")
        for p in g:
            print(f"  {p}")
    return 0


def cmd_ocr(args):
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}")
        return 1
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        print("未安装 OCR 引擎，请先执行：python -m pip install rapidocr-onnxruntime")
        return 1
    print("识别中（首次运行需初始化模型，稍等）...")
    engine = RapidOCR()
    result, _ = engine(str(path))
    if not result:
        print("未识别到文字（可能是纯图片或文字太小/太模糊）")
        return 0
    lines = clean_ocr_lines(result)
    if not lines:
        print("识别到内容，但均为低置信度/乱码，可能图片文字渲染异常")
        return 0
    print(f"识别到 {len(lines)} 处文字：")
    for text in lines:
        print(f"  {text}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="图片识别/查重工具")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_info = sub.add_parser("info", help="识别图片元信息")
    p_info.add_argument("path")
    p_info.set_defaults(func=cmd_info)
    p_hash = sub.add_parser("hash", help="生成图片指纹")
    p_hash.add_argument("path")
    p_hash.set_defaults(func=cmd_hash)
    p_cmp = sub.add_parser("compare", help="比较两张图相似度")
    p_cmp.add_argument("a")
    p_cmp.add_argument("b")
    p_cmp.set_defaults(func=cmd_compare)
    p_scan = sub.add_parser("scan", help="批量查找相似/重复图片")
    p_scan.add_argument("folder")
    p_scan.add_argument("--threshold", type=float, default=90.0,
                        help="相似度阈值，默认 90")
    p_scan.set_defaults(func=cmd_scan)
    p_ocr = sub.add_parser("ocr", help="识别图片中的文字")
    p_ocr.add_argument("path")
    p_ocr.set_defaults(func=cmd_ocr)
    args = parser.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
