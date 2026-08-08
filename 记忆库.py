# -*- coding: utf-8 -*-
"""
Mem0 自主记忆库（AI 智能体长期记忆）

自动从对话/文本中提取关键事实存入本地向量库，之后可按语义召回。
实现"我上次记住了什么、下次能想起来"的自主学习记忆。

后端（全部本地 + DeepSeek API）：
  - 记忆抽取 LLM : DeepSeek（读取环境变量 DEEPSEEK_API_KEY）
  - 向量库        : faiss 本地文件（mem0_store/ 目录，无需联网服务）
  - 文本嵌入      : HuggingFace 本地模型 multi-qa-MiniLM-L6-cos-v1

用法：
  python 记忆库.py 记住 "文本内容" [--用户 admin] [--元数据 key=value]
  python 记忆库.py 回想 "问题"    [--用户 admin]
  python 记忆库.py 全部 [--用户 admin]
  python 记忆库.py 遗忘 <记忆id>  [--用户 admin]
  python 记忆库.py 清空 [--用户 admin]

示例：
  python 记忆库.py 记住 "用户老张是项目经理，负责云岭高速项目" --用户 admin
  python 记忆库.py 回想 "谁是项目经理？在做什么项目？" --用户 admin
"""

from __future__ import annotations

import argparse
import os
import sys

# 关闭 Mem0 遥测，避免多余网络请求与测试向量
os.environ["MEM0_TELEMETRY"] = "false"

_STORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mem0_store")

_MEMORY = None


def _get_memory():
    """懒加载 Memory 实例（模型首次使用会自动下载，需联网）。"""
    global _MEMORY
    if _MEMORY is not None:
        return _MEMORY
    from mem0 import Memory

    config = {
        "llm": {
            "provider": "deepseek",
            "config": {"model": "deepseek-chat"},
        },
        "embedder": {
            "provider": "huggingface",
            "config": {"model": "multi-qa-MiniLM-L6-cos-v1"},
        },
        "vector_store": {
            "provider": "faiss",
            "config": {
                "collection_name": "memories",
                "path": _STORE_DIR,
                # MiniLM-L6 输出 384 维，必须与向量库一致
                "embedding_model_dims": 384,
            },
        },
    }
    _MEMORY = Memory.from_config(config)
    return _MEMORY


def cmd_记住(args):
    m = _get_memory()
    if not args.用户:
        print("请指定 --用户")
        return 1
    print("正在提取并保存记忆（首次运行需下载嵌入模型）...")
    kwargs = {"user_id": args.用户, "metadata": args.元数据 or None}
    result = m.add(args.文本, **kwargs)
    added = result.get("results", [])
    print(f"已保存 {len(added)} 条记忆:")
    for item in added:
        print(f"  [{item.get('id')}] {item.get('memory')}")
    return 0


def cmd_回想(args):
    m = _get_memory()
    if not args.用户:
        print("请指定 --用户")
        return 1
    result = m.search(args.问题, filters={"user_id": args.用户})
    results = result.get("results", [])
    if not results:
        print("未找到相关记忆。")
        return 0
    print(f"召回 {len(results)} 条相关记忆：")
    for i, item in enumerate(results, 1):
        score = item.get("score")
        score = f"（相关度 {score:.2f}）" if score is not None else ""
        print(f"  {i}. {item.get('memory')}{score}")
    return 0


def cmd_全部(args):
    m = _get_memory()
    result = m.get_all(filters={"user_id": args.用户})
    results = result.get("results", [])
    if not results:
        print("该用户还没有记忆。")
        return 0
    print(f"共 {len(results)} 条记忆：")
    for item in results:
        memory = item.get("memory")
        print(f"  [{item.get('id')}] {memory}")
    return 0


def cmd_遗忘(args):
    m = _get_memory()
    if not args.记忆id:
        print("请提供要遗忘的记忆 id（可用 全部 子命令查看）")
        return 1
    m.delete(args.记忆id)
    print(f"已删除记忆 {args.记忆id}")
    return 0


def cmd_清空(args):
    m = _get_memory()
    result = m.get_all(filters={"user_id": args.用户})
    ids = [item.get("id") for item in result.get("results", [])]
    if not ids:
        print("没有可清空的记忆。")
        return 0
    for mid in ids:
        m.delete(mid)
    print(f"已清空 {len(ids)} 条记忆（用户 {args.用户}）")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Mem0 自主记忆库")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("记住", help="提取并保存记忆")
    p_add.add_argument("文本")
    p_add.add_argument("--用户", default=None)
    p_add.add_argument("--元数据", default=None, help="如 来源=照片上传")
    p_add.set_defaults(func=cmd_记住)
    p_sea = sub.add_parser("回想", help="按语义召回记忆")
    p_sea.add_argument("问题")
    p_sea.add_argument("--用户", default=None)
    p_sea.set_defaults(func=cmd_回想)
    p_all = sub.add_parser("全部", help="列出某用户全部记忆")
    p_all.add_argument("--用户", default=None)
    p_all.set_defaults(func=cmd_全部)
    p_del = sub.add_parser("遗忘", help="按 id 删除一条记忆")
    p_del.add_argument("记忆id")
    p_del.add_argument("--用户", default=None)
    p_del.set_defaults(func=cmd_遗忘)
    p_clr = sub.add_parser("清空", help="清空某用户全部记忆")
    p_clr.add_argument("--用户", default=None)
    p_clr.set_defaults(func=cmd_清空)
    args = parser.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
