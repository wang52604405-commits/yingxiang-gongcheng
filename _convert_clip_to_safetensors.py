# -*- coding: utf-8 -*-
"""一次性脚本：把 chinese-clip-vit-base-patch16 的 pytorch_model.bin 转为 safetensors。

原因：torch 2.5.1 被 transformers 5.x 禁止 torch.load 加载 .bin 权重（CVE-2025-32434），
但 safetensors 格式不受限制。本脚本用 torch.load 直接转换一次，之后从本地加载。
运行：python _convert_clip_to_safetensors.py
"""

from pathlib import Path

from huggingface_hub import hf_hub_download

MODEL_ID = "OFA-Sys/chinese-clip-vit-base-patch16"
LOCAL = Path(__file__).resolve().parent / "models" / "chinese-clip-vit-base-patch16"

FILES = ["config.json", "preprocessor_config.json", "vocab.txt", "pytorch_model.bin"]


def main():
    LOCAL.mkdir(parents=True, exist_ok=True)
    print(f"下载模型文件到 {LOCAL} ...")
    for fname in FILES:
        path = hf_hub_download(repo_id=MODEL_ID, filename=fname, local_dir=str(LOCAL))
        print("  ", path)

    import torch
    import safetensors.torch as st

    bin_path = LOCAL / "pytorch_model.bin"
    out_path = LOCAL / "model.safetensors"
    if out_path.exists():
        print(f"model.safetensors 已存在，跳过转换")
    else:
        print("转换 pytorch_model.bin -> model.safetensors ...")
        sd = torch.load(str(bin_path), map_location="cpu", weights_only=True)
        sd = {k: v.contiguous() for k, v in sd.items()}
        st.save_file(sd, str(out_path))
        print(f"转换完成，共 {len(sd)} 个张量")
        bin_path.unlink()
    print("完成。本地模型目录:", LOCAL)


if __name__ == "__main__":
    main()
