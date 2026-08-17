# -*- coding: utf-8 -*-
"""
自动学习记忆.py —— Mem0 记忆库自动学习桥

把 Codex 聊天记录（项目聊天记忆-工程影像管理平台/原始记录_*.jsonl）
增量地自动学习进本地记忆库（记忆库.py / mem0_store/），之后可按语义召回。

设计要点：
  - 增量：状态文件 mem0_store/auto_learn_state.json 记录每个文件的已学行数，
    每次只学新增内容，重复运行不重复花 API 费用。
  - 去重：按文本块哈希记录已学内容，--强制 重学也不会重复入库存。
  - 成本控制：--上限 控制单次最多学习多少块，配合计划任务定期慢慢学完。
  - 只学用户消息（默认），避免把大量推理/回复噪声灌进记忆库。

用法：
  python 自动学习记忆.py              增量学习（默认单次最多 40 块）
  python 自动学习记忆.py --上限 100   调整单次学习块数上限
  python 自动学习记忆.py --强制       忽略进度状态，从头重学（按哈希去重）
  python 自动学习记忆.py --含助手     同时学习助手回复文本
  python 自动学习记忆.py --文件 会话04 只学习文件名包含关键字的文件
  python 自动学习记忆.py --看状态     只看学习进度，不发起学习
  python 自动学习记忆.py --服务器 http://服务器IP:5199 --密钥 xxx
                                     学到的记忆写入服务器记忆库（代替本机）
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    requests = None

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE, "项目聊天记忆-工程影像管理平台")
MEMORY_SCRIPT = os.path.join(BASE, "记忆库.py")
STATE_FILE = os.path.join(BASE, "mem0_store", "auto_learn_state.json")

CHUNK_CHARS = 2200          # 每块文本约 2200 字符，交给记忆库 LLM 抽取事实
DEFAULT_CAP = 40            # 单次运行默认最多学习多少块
USER_ID = "admin"


class RemoteMemory:
    """把记忆写入服务器记忆库 API（记忆库服务器.py）。"""

    def __init__(self, base: str, key: str):
        self.base = base.rstrip("/")
        self.key = key

    def add(self, text: str, user_id: str, metadata: dict | None = None):
        if requests is None:
            raise RuntimeError("远程模式需要 requests，请先 pip install requests")
        resp = requests.post(
            self.base + "/remember",
            json={"text": text, "user_id": user_id, "metadata": metadata},
            headers={"X-API-Key": self.key},
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()


def load_memory_module():
    """加载本地记忆库 记忆库.py，复用它的 mem0 配置与实例。"""
    spec = importlib.util.spec_from_file_location("jyk_mem", MEMORY_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"files": {}, "chunks": []}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_CONTEXT_BLOCK_RE = [
    re.compile(r"<environment_context>.*?</environment_context>", re.S),
    re.compile(r"<in-app-browser-context[^>]*>.*?</in-app-browser-context>", re.S),
    re.compile(r"<permissions[^>]*>.*?</permissions>", re.S),
]

_SECRET_RE = [
    (re.compile(r"(密码|口令|password|secret)\s*[:：=]\s*[^\s，。；、]+", re.I),
     lambda m: m.group(1) + ": [已隐藏]"),
    (re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|gho_[A-Za-z0-9_\-]{8,}|ghp_[A-Za-z0-9_\-]{8,})"),
     lambda m: "[已隐藏]"),
    (re.compile(r"(ALBUM_SERVER_SECRET|DEEPSEEK_API_KEY|OPENAI_API_KEY)\s*=\s*\S+"),
     lambda m: m.group(1) + "=[已隐藏]"),
]


def clean_text(text: str) -> str:
    """去掉系统上下文块，并把密码/密钥等敏感值打码，避免学进记忆库。"""
    if not text:
        return ""
    for rx in _CONTEXT_BLOCK_RE:
        text = rx.sub("", text)
    for rx, repl in _SECRET_RE:
        text = rx.sub(repl, text)
    return text.strip()


def iter_records(path: str):
    """逐行解析 jsonl，产出 (时间, 角色, 文本)。角色空表示无法判断。"""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ts, role, text = parse_record(rec)
            if text:
                yield ts, role, text


def parse_record(rec: dict):
    """从一条 jsonl 记录中解析 (时间, 角色, 文本)。"""
    ts = rec.get("timestamp") or ""
    ptype = rec.get("type") or ""
    payload = rec.get("payload") or {}
    if not ts:
        ts = payload.get("timestamp") or ""
    role = payload.get("role") or ""
    text = ""
    if ptype == "response_item" and payload.get("type") == "message":
        for item in payload.get("content") or []:
            if isinstance(item, dict) and item.get("text"):
                text += item["text"] + "\n"
    elif ptype == "event_msg" and payload.get("type") == "user_message":
        text = payload.get("message") or ""
    return ts, role, clean_text(text)


def acquire_lock():
    """单实例锁：防止计划任务重叠运行。返回文件句柄或 None。"""
    lock_path = os.path.join(BASE, "mem0_store", "auto_learn.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        return fd
    except FileExistsError:
        try:
            if time.time() - os.path.getmtime(lock_path) > 2 * 3600:
                os.remove(lock_path)
                return acquire_lock()
        except FileNotFoundError:
            return acquire_lock()
        return None


def release_lock(fd) -> None:
    lock_path = os.path.join(BASE, "mem0_store", "auto_learn.lock")
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        os.remove(lock_path)
    except FileNotFoundError:
        pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def learn_file(path: str, state: dict, include_assistant: bool,
               cap: int, learned: list, chunk_hashes: set,
               memory=None) -> None:
    key = os.path.basename(path)
    files_state = state["files"]
    info = files_state.get(key, {"lines": 0, "size": 0})
    size = os.path.getsize(path)

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start = 0
    if info.get("lines"):
        start = info["lines"]
    # 文件被改写/截断过（行数倒退或变小），从头重学
    if start > len(lines) or (size < info.get("size", 0) and start >= len(lines)):
        start = 0

    if start >= len(lines):
        files_state[key] = {"lines": len(lines), "size": size}
        return

    m = None
    checkpoint = start
    buf: list[str] = []
    buf_len = 0

    def flush(up_to_line: int) -> bool:
        nonlocal buf, buf_len
        if not buf:
            return True
        text = "\n".join(buf)
        buf = []
        buf_len = 0
        h = sha256(text)
        if h in chunk_hashes:
            return True
        nonlocal m
        if m is None:
            m = memory if memory is not None else load_memory_module()._get_memory()
        meta = {"来源": key, "学习时间": now_iso()}
        try:
            res = m.add(text, user_id=USER_ID, metadata=meta)
            n = len((res or {}).get("results") or [])
            chunk_hashes.add(h)
            learned[0] += 1
            preview = text.replace("\n", " ")[:70]
            print(f"[{learned[0]:>3}] {key} 提取 {n} 条: {preview}")
            nonlocal checkpoint
            checkpoint = up_to_line
            return True
        except Exception as e:
            print(f"  !! 学习失败（下次重试）: {e}", file=sys.stderr)
            return False

    for idx in range(start, len(lines)):
        if learned[0] >= cap:
            break
        line = lines[idx]
        try:
            rec = json.loads(line.strip())
        except Exception:
            continue
        _, role, text = parse_record(rec)
        if not text:
            continue

        if role == "assistant" and not include_assistant:
            continue
        if role not in ("user", "assistant"):
            continue

        buf.append(text)
        buf_len += len(text) + 1
        if buf_len >= CHUNK_CHARS:
            if not flush(idx + 1):
                break

    if buf and learned[0] < cap:
        flush(len(lines))

    files_state[key] = {"lines": checkpoint, "size": size}


def show_status(state: dict) -> None:
    print("=== 自动学习进度 ===")
    if not state["files"]:
        print("还没有学习过任何记录。")
    for key, info in sorted(state["files"].items()):
        print(f"  {key}: 已学 {info.get('lines', 0)} 行")
    print(f"已学文本块去重表: {len(state.get('chunks', []))} 块")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mem0 记忆库自动学习桥")
    parser.add_argument("--上限", type=int, default=DEFAULT_CAP, dest="cap")
    parser.add_argument("--强制", action="store_true", dest="force")
    parser.add_argument("--含助手", action="store_true", dest="include_assistant")
    parser.add_argument("--文件", default=None, dest="only")
    parser.add_argument("--看状态", action="store_true", dest="status")
    parser.add_argument("--服务器", default=None, dest="server")
    parser.add_argument("--密钥", default=None, dest="key")
    args = parser.parse_args()

    state = load_state()
    if args.status:
        show_status(state)
        return 0

    fd = acquire_lock()
    if fd is None:
        print("另一个学习进程正在运行，本次跳过。")
        return 0
    try:
        pattern = os.path.join(LOG_DIR, "原始记录_*.jsonl")
        files = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
        if args.only:
            files = [p for p in files if args.only in os.path.basename(p)]
        if not files:
            print(f"未找到聊天记录: {pattern}")
            return 1

        chunk_hashes = set(state.get("chunks", []))
        learned = [0]
        memory = None
        if args.server:
            memory = RemoteMemory(args.server, args.key or "")
        for path in files:
            if learned[0] >= args.cap:
                break
            learn_file(path, state, args.include_assistant, args.cap,
                       learned, chunk_hashes, memory)

        state["chunks"] = sorted(chunk_hashes)
        save_state(state)

        print(f"\n本次新学习 {learned[0]} 块（上限 {args.cap}）。")
        if learned[0] >= args.cap:
            print("还没学完，计划任务下次运行会继续。")
        else:
            print("全部记录已学完，之后新增聊天记录会自动增量学习。")
    finally:
        release_lock(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
