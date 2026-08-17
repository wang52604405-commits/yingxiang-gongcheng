# -*- coding: utf-8 -*-
"""
记忆库客户端.py —— 从任意电脑接入服务器的记忆库。

零依赖（只用 Python 标准库），拷到任何电脑即可用。

用法：
  1. 首次接入配置一次：
     python 记忆库客户端.py 配置 --服务器 http://47.95.221.66:5199 --密钥 xxxxx
     （配置保存到 ~/.memory-client.json，之后不用再带参数）
  2. 日常使用：
     python 记忆库客户端.py 记住 "项目经理老张负责云岭高速项目"
     python 记忆库客户端.py 回想 "谁是项目经理？"
     python 记忆库客户端.py 全部
     python 记忆库客户端.py 健康

也可临时指定：--服务器 http://... --密钥 xxx（或环境变量 MEMORY_SERVER / MEMORY_API_KEY）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.error
import urllib.request

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".memory-client.json")

if sys.stdout and getattr(sys.stdout, "reconfigure", None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_config() -> dict:
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    cfg.setdefault("服务器", os.environ.get("MEMORY_SERVER", "http://127.0.0.1:5199"))
    cfg.setdefault("密钥", os.environ.get("MEMORY_API_KEY", ""))
    return cfg


def save_config(server: str, key: str) -> None:
    data = {"服务器": server, "密钥": key}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except Exception:
        pass
    print(f"配置已保存: {CONFIG_PATH}")


def call(cfg: dict, method: str, path: str, body: dict | None = None) -> dict:
    url = cfg["服务器"].rstrip("/") + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if cfg.get("密钥"):
        req.add_header("X-API-Key", cfg["密钥"])
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"请求失败 HTTP {e.code}: {msg}")
    except Exception as e:
        raise SystemExit(f"连接失败: {e}")


def cmd_配置(args, cfg):
    save_config(args.服务器, args.密钥)


def cmd_记住(args, cfg):
    body = {"text": args.文本, "user_id": args.用户}
    if args.元数据:
        meta = {}
        for pair in args.元数据.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                meta[k.strip()] = v.strip()
        body["metadata"] = meta
    print("正在提取并保存记忆...")
    result = call(cfg, "POST", "/remember", body)
    for item in result.get("results") or []:
        print(f"  [{item.get('id')}] {item.get('memory')}")


def cmd_回想(args, cfg):
    result = call(cfg, "POST", "/recall",
                  {"query": args.问题, "user_id": args.用户, "top_k": args.条数})
    results = result.get("results") or []
    if not results:
        print("未找到相关记忆。")
        return
    print(f"召回 {len(results)} 条相关记忆：")
    for i, item in enumerate(results, 1):
        score = item.get("score")
        s = f"（相关度 {score:.2f}）" if score is not None else ""
        print(f"  {i}. {item.get('memory')}{s}")


def cmd_全部(args, cfg):
    result = call(cfg, "GET", f"/memories?user_id={urllib.parse.quote(args.用户)}")
    results = result.get("results") or []
    if not results:
        print("该用户还没有记忆。")
        return
    print(f"共 {len(results)} 条记忆：")
    for item in results:
        print(f"  [{item.get('id')}] {item.get('memory')}")


def cmd_健康(args, cfg):
    print(call(cfg, "GET", "/health"))


def main() -> int:
    parser = argparse.ArgumentParser(description="记忆库远程客户端")
    parser.add_argument("--服务器", default=None)
    parser.add_argument("--密钥", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cfg = sub.add_parser("配置", help="保存服务器地址与密钥")
    p_cfg.set_defaults(func=cmd_配置)

    p_add = sub.add_parser("记住")
    p_add.add_argument("文本")
    p_add.add_argument("--用户", default="admin")
    p_add.add_argument("--元数据", default=None)
    p_add.set_defaults(func=cmd_记住)

    p_sea = sub.add_parser("回想")
    p_sea.add_argument("问题")
    p_sea.add_argument("--用户", default="admin")
    p_sea.add_argument("--条数", type=int, default=20)
    p_sea.set_defaults(func=cmd_回想)

    p_all = sub.add_parser("全部")
    p_all.add_argument("--用户", default="admin")
    p_all.set_defaults(func=cmd_全部)

    p_health = sub.add_parser("健康")
    p_health.set_defaults(func=cmd_健康)

    for sp in (p_cfg, p_add, p_sea, p_all, p_health):
        sp.add_argument("--服务器", default=None)
        sp.add_argument("--密钥", default=None)

    args = parser.parse_args()
    cfg = load_config()
    if args.服务器:
        cfg["服务器"] = args.服务器
    if args.密钥:
        cfg["密钥"] = args.密钥
    args.func(args, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
