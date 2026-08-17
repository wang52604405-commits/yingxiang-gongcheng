# -*- coding: utf-8 -*-
"""
记忆库服务器.py —— 把本地 Mem0 记忆库变成 HTTP API，部署到服务器后任意电脑可接入。

依赖：pip install flask mem0ai faiss-cpu sentence-transformers
环境变量：
  DEEPSEEK_API_KEY  记忆抽取用（记忆库原有配置）
  MEMORY_API_KEY    API 访问密钥；不设置则首次启动自动生成并保存到 mem0_store/api_key.txt
  MEM0_STORE_DIR    记忆存放目录（默认脚本旁的 mem0_store/）

用法：
  python 记忆库服务器.py                 # 默认 127.0.0.1:5199
  python 记忆库服务器.py --host 0.0.0.0 --port 5199

API：
  GET  /health                      健康检查（不需要密钥）
  POST /remember   {"text": "...", "user_id": "admin", "metadata": {...}}
  POST /recall     {"query": "...", "user_id": "admin", "top_k": 20}
  GET  /memories?user_id=admin      全部记忆
  DELETE /memories/<id>?user_id=admin  删除一条

鉴权：请求头 X-API-Key 或 URL 参数 key。
"""

from __future__ import annotations

import argparse
import hmac
import os
import secrets

from flask import Flask, jsonify, request

BASE = os.path.dirname(os.path.abspath(__file__))

_MEMORY = None


def _get_memory():
    """懒加载 mem0 实例（首次会下载嵌入模型，约 90MB）。"""
    global _MEMORY
    if _MEMORY is not None:
        return _MEMORY
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "jyk_mem", os.path.join(BASE, "记忆库.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _MEMORY = mod._get_memory()
    return _MEMORY


def _load_or_create_api_key() -> str:
    env = os.environ.get("MEMORY_API_KEY")
    if env:
        return env.strip()
    store_dir = os.environ.get("MEM0_STORE_DIR") or os.path.join(BASE, "mem0_store")
    key_file = os.path.join(store_dir, "api_key.txt")
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(16)
    os.makedirs(store_dir, exist_ok=True)
    with open(key_file, "w", encoding="utf-8") as f:
        f.write(key)
    print(f"[首次启动] 已生成 API 密钥: {key}")
    print(f"         已保存到 {key_file}，客户端配置时使用。")
    return key


API_KEY = _load_or_create_api_key()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_000_000  # 1MB 上限


@app.before_request
def _auth():
    if request.path == "/health":
        return None
    key = request.headers.get("X-API-Key") or request.args.get("key") or ""
    if not key or not hmac.compare_digest(key, API_KEY):
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.errorhandler(413)
def _too_large(_e):
    return jsonify({"error": "request too large"}), 413


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "memory", "version": 1})


@app.post("/remember")
def remember():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    user_id = data.get("user_id") or "admin"
    metadata = data.get("metadata") or None
    try:
        result = _get_memory().add(text, user_id=user_id, metadata=metadata)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/recall")
def recall():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    user_id = data.get("user_id") or "admin"
    top_k = int(data.get("top_k") or 20)
    try:
        result = _get_memory().search(
            query, limit=top_k, filters={"user_id": user_id}
        )
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/memories")
def memories():
    user_id = request.args.get("user_id") or "admin"
    try:
        result = _get_memory().get_all(filters={"user_id": user_id})
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.delete("/memories/<mid>")
def delete_memory(mid):
    try:
        _get_memory().delete(mid)
        return jsonify({"deleted": mid}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def main() -> int:
    parser = argparse.ArgumentParser(description="Mem0 记忆库 HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5199)
    parser.add_argument("--预热", action="store_true", dest="warm",
                        help="启动时预加载模型，避免首次请求慢")
    args = parser.parse_args()

    if args.warm:
        print("正在预加载记忆模型...")
        _get_memory()
        print("模型已就绪。")

    print(f"记忆库服务已启动: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
