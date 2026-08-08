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
"""

# 老库升级：accounts 表缺少的新列，启动时补上
ACCOUNTS_EXTRA_COLUMNS = {
    "invite_code": "TEXT",
    "inviter_id": "INTEGER DEFAULT 0",
    "invite_reward_months": "INTEGER DEFAULT 0",
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
    """幂等迁移：建 invites 表；检查 accounts 表缺列则 ALTER 补上（老库兜底）。"""
    conn = connect()
    try:
        conn.execute(INVITES_DDL)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)")}
        for name, decl in ACCOUNTS_EXTRA_COLUMNS.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE accounts ADD COLUMN {name} {decl}")
        conn.commit()
    finally:
        conn.close()


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    migrate()
