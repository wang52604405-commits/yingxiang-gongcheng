# -*- coding: utf-8 -*-
"""
图片AI识别（CLIP 看懂图片内容，零依赖网络API）

用开源中文 CLIP 模型把图片内容映射到中文标签，回答"这张照片里有什么"——
人物/施工机械/工地场景等，并给出一句话描述。模型首次运行自动从
HuggingFace 下载（约 1GB），之后本地缓存。

用法：
  python 图片AI识别.py 识别 <图片路径> [--labels "自定义,标签" --top 5]
  python 图片AI识别.py 描述 <图片路径> [--top 3]
  python 图片AI识别.py 列出标签

示例：
  python 图片AI识别.py 识别 照片.jpg
  python 图片AI识别.py 识别 照片.jpg --labels "安全帽,未戴安全帽,钢筋,脚手架"
  python 图片AI识别.py 描述 照片.jpg
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

# 工程场景常用中文标签（可按需在 --labels 里覆盖）
DEFAULT_LABELS = [
    "施工人员", "多人施工", "安全帽", "挖掘机", "推土机", "装载机",
    "塔吊", "吊车", "搅拌车", "压路机", "打桩机", "钻孔机",
    "工程车辆", "货车", "卡车", "轿车", "摩托车",
    "施工现场", "道路施工", "桥梁施工", "隧道施工", "土方开挖",
    "钢筋", "脚手架", "混凝土结构", "挡墙护坡", "测量仪器",
    "施工围挡", "施工机械", "工地全景",
    "办公室", "文档表格", "会议室", "仓库",
    "无人机航拍", "夜景", "雨天", "水面河流", "森林绿化", "天空",
]

_LOADED = {"model": None, "processor": None, "device": "cpu"}
_LOAD_LOCK = threading.Lock()

# 本地已转换好的模型（safetensors，避免 .bin 被 torch 2.5 禁止加载）；不存在则回退远程
_MODEL_ID = "OFA-Sys/chinese-clip-vit-base-patch16"
_LOCAL_MODEL = Path(__file__).resolve().parent / "models" / "chinese-clip-vit-base-patch16"


def _device():
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _get_clip():
    """懒加载 CLIP 模型（首次运行会下载模型，耗时较长）。"""
    if _LOADED["model"] is not None:
        return _LOADED["model"], _LOADED["processor"]
    with _LOAD_LOCK:
        if _LOADED["model"] is not None:
            return _LOADED["model"], _LOADED["processor"]
        import torch
        from transformers import ChineseCLIPModel, ChineseCLIPProcessor

        _LOADED["device"] = _device()
        model_dir = _LOCAL_MODEL if _LOCAL_MODEL.exists() else _MODEL_ID
        print(f"加载 CLIP 模型（设备: {_LOADED['device']}，来源: {model_dir}）...")
        _LOADED["model"] = ChineseCLIPModel.from_pretrained(model_dir).to(_LOADED["device"])
        _LOADED["model"].eval()
        _LOADED["processor"] = ChineseCLIPProcessor.from_pretrained(model_dir)
        print("模型加载完成。")
        return _LOADED["model"], _LOADED["processor"]


def _open(path: Path) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def classify(image: Image.Image, labels: list[str], top_n: int = 5):
    """零样本分类：返回 [(标签, 概率百分比)]，按概率降序。"""
    import torch

    model, processor = _get_clip()
    inputs = processor(
        text=labels, images=image, return_tensors="pt", padding=True
    ).to(_LOADED["device"])
    with torch.no_grad():
        outputs = model(**inputs)
        probs = outputs.logits_per_image.softmax(dim=1)[0]
    scored = sorted(zip(labels, probs.tolist()), key=lambda x: -x[1])
    return [(label, round(score * 100, 1)) for label, score in scored[:top_n]]


def cmd_识别(args):
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}")
        return 1
    labels = [s.strip() for s in args.labels.split(",") if s.strip()] or DEFAULT_LABELS
    print(f"识别图片: {path}  （{len(labels)} 个候选标签）")
    print("识别中...")
    try:
        results = classify(_open(path), labels, args.top)
    except Exception as e:
        print(f"识别失败: {e}")
        return 1
    print(f"\n图片内容（置信度 Top {len(results)}）:")
    for label, score in results:
        print(f"  {label:　<8}  {score:>5.1f}%")
    return 0


def cmd_描述(args):
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}")
        return 1
    labels = [s.strip() for s in args.labels.split(",") if s.strip()] or DEFAULT_LABELS
    print(f"识别图片: {path}")
    print("识别中...")
    try:
        results = classify(_open(path), labels, args.top)
    except Exception as e:
        print(f"识别失败: {e}")
        return 1
    top = [label for label, _ in results]
    best, best_score = results[0]
    desc = f"这张图片{('主要' if best_score >= 60 else '疑似')}为：{'、'.join(top)}。"
    print(f"\n{desc}")
    if best_score < 30:
        print("（置信度较低，可能与内置标签都不匹配，可加 --labels 自定义标签重试）")
    return 0


def cmd_列出标签(_args):
    print("内置标签:")
    for label in DEFAULT_LABELS:
        print(f"  {label}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="图片AI识别（CLIP 看懂图片内容）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_rec = sub.add_parser("识别", help="识别图片内容（标签+置信度）")
    p_rec.add_argument("path")
    p_rec.add_argument("--labels", default="", help="逗号分隔的自定义标签")
    p_rec.add_argument("--top", type=int, default=5)
    p_rec.set_defaults(func=cmd_识别)
    p_desc = sub.add_parser("描述", help="一句话描述图片内容")
    p_desc.add_argument("path")
    p_desc.add_argument("--labels", default="", help="逗号分隔的自定义标签")
    p_desc.add_argument("--top", type=int, default=3)
    p_desc.set_defaults(func=cmd_描述)
    p_list = sub.add_parser("列出标签", help="查看内置标签")
    p_list.set_defaults(func=cmd_列出标签)
    args = parser.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
