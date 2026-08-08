# -*- coding: utf-8 -*-
"""SQLite 数据库层。客户量增长后可按同样表结构迁移到 MySQL。"""

from __future__ import annotations

import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name  TEXT DEFAULT '',
    role          TEXT DEFAULT 'user',
    status        TEXT DEFAULT 'active',
    created_at    TEXT DEFAULT (datetime('now', 'localtime')),
    notes         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS licenses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL,
    license_type  TEXT NOT NULL DEFAULT 'term',
    valid_days    INTEGER DEFAULT 0,
    machine_limit INTEGER DEFAULT 3,
    issued_at     TEXT DEFAULT (datetime('now', 'localtime')),
    expires_at    TEXT DEFAULT '',
    active        INTEGER DEFAULT 1,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS machines (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    machine_id TEXT NOT NULL,
    bound_at   TEXT DEFAULT (datetime('now', 'localtime')),
    last_seen  TEXT DEFAULT (datetime('now', 'localtime')),
    active     INTEGER DEFAULT 1,
    UNIQUE (account_id, machine_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS invites (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    inviter_id         INTEGER NOT NULL,           -- 邀请人 account.id
    invitee_account_id INTEGER UNIQUE NOT NULL,    -- 被邀请人 account.id（一人一邀请，防重）
    created_at         TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (inviter_id) REFERENCES accounts(id),
    FOREIGN KEY (invitee_account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS cloud_projects (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL,
    project_code  TEXT NOT NULL,
    project_name  TEXT DEFAULT '',
    unit_name     TEXT DEFAULT '',
    part_name     TEXT DEFAULT '',
    thumb_count   INTEGER DEFAULT 0,
    synced_at     TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE (account_id, project_code),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS cloud_thumbs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    photo_name    TEXT NOT NULL,
    thumb_b64     TEXT NOT NULL,          -- 模糊缩略图 base64（小尺寸，限长）
    order_index   INTEGER DEFAULT 0,
    synced_at     TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE (project_id, photo_name),
    FOREIGN KEY (project_id) REFERENCES cloud_projects(id)
);

CREATE TABLE IF NOT EXISTS mail_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code_key   TEXT UNIQUE NOT NULL,      -- reset:{account} / 注册账号
    code       TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS product_settings (
    setting_key TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT DEFAULT (datetime('now', 'localtime')),
    updated_by  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS client_error_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER,
    fingerprint     TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'desktop',
    severity        TEXT NOT NULL DEFAULT 'error',
    error_type      TEXT NOT NULL DEFAULT '',
    message         TEXT NOT NULL DEFAULT '',
    stack           TEXT NOT NULL DEFAULT '',
    context_json    TEXT NOT NULL DEFAULT '{}',
    app_version     TEXT NOT NULL DEFAULT '',
    machine_id      TEXT NOT NULL DEFAULT '',
    client_time     TEXT NOT NULL DEFAULT '',
    request_ip      TEXT NOT NULL DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    resolved        INTEGER DEFAULT 0,
    resolved_at     TEXT NOT NULL DEFAULT '',
    resolution_note TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_error_logs_created
ON client_error_logs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_error_logs_account
ON client_error_logs(account_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_error_logs_fingerprint
ON client_error_logs(fingerprint, created_at DESC);
"""

# 老库升级：accounts 表缺少的新列，启动时补上
ACCOUNTS_EXTRA_COLUMNS = {
    "invite_code": "TEXT",
    "inviter_id": "INTEGER DEFAULT 0",
    "invite_reward_months": "INTEGER DEFAULT 0",
    "email": "TEXT DEFAULT ''",
}

INVITES_EXTRA_COLUMNS = {
    "status": "TEXT DEFAULT 'pending'",
    "qualified_at": "TEXT DEFAULT ''",
    "device_hash": "TEXT DEFAULT ''",
    "ip_hash": "TEXT DEFAULT ''",
}


INVITES_DDL = """
CREATE TABLE IF NOT EXISTS invites (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    inviter_id         INTEGER NOT NULL,
    invitee_account_id INTEGER UNIQUE NOT NULL,
    created_at         TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (inviter_id) REFERENCES accounts(id),
    FOREIGN KEY (invitee_account_id) REFERENCES accounts(id)
)
"""


def migrate() -> None:
    """幂等迁移：只补表和列，不重建旧表，不改写现有业务数据。"""
    conn = connect()
    try:
        conn.execute(INVITES_DDL)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)")}
        for name, decl in ACCOUNTS_EXTRA_COLUMNS.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE accounts ADD COLUMN {name} {decl}")
        invite_cols = {row["name"] for row in conn.execute("PRAGMA table_info(invites)")}
        for name, decl in INVITES_EXTRA_COLUMNS.items():
            if name not in invite_cols:
                conn.execute(f"ALTER TABLE invites ADD COLUMN {name} {decl}")
        conn.commit()
    finally:
        conn.close()


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    migrate()
