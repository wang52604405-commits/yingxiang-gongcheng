# -*- coding: utf-8 -*-
"""SQLite 数据库层。客户量增长后可按同样表结构迁移到 MySQL。"""

from __future__ import annotations

import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_account_access (
    account_id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_account_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    actor_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_usage_daily (
    day TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    PRIMARY KEY(day, account_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_admin_usage_last ON admin_usage_daily(last_seen);
CREATE TABLE IF NOT EXISTS admin_metrics_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO admin_metrics_meta VALUES ('started_at', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name  TEXT DEFAULT '',
    role          TEXT DEFAULT 'user',
    status        TEXT DEFAULT 'active',
    mobile_auth_version INTEGER NOT NULL DEFAULT 0,
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


# 移动端 V1 采用纯增量表。表名与旧 cloud_projects/cloud_thumbs 分开，避免
# 改写既有云预览数据；所有业务唯一键都包含 account_id，保证租户隔离。
MOBILE_SCHEMA = """
CREATE TABLE IF NOT EXISTS mobile_upload_usage (
    project_owner_account_id INTEGER NOT NULL,
    photo_uuid TEXT NOT NULL,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_owner_account_id, photo_uuid)
);
CREATE TABLE IF NOT EXISTS project_watermark_settings (
    project_owner_account_id INTEGER NOT NULL,
    project_id TEXT NOT NULL,
    logo_id TEXT NOT NULL DEFAULT 'crec',
    contractor TEXT NOT NULL DEFAULT '',
    updated_by_account_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_owner_account_id, project_id)
);
CREATE TABLE IF NOT EXISTS project_photo_security (
    project_owner_account_id INTEGER NOT NULL, project_id TEXT NOT NULL,
    delete_password_hash TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(project_owner_account_id, project_id)
);
CREATE TABLE IF NOT EXISTS mobile_photo_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, project_owner_account_id INTEGER NOT NULL,
    project_id TEXT NOT NULL, photo_uuid TEXT NOT NULL, action TEXT NOT NULL,
    payload_json TEXT NOT NULL, actor_account_id INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mobile_photo_changes_project ON mobile_photo_changes(project_owner_account_id,project_id,id);

CREATE TABLE IF NOT EXISTS wechat_bindings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL,
    app_id        TEXT NOT NULL,
    openid        TEXT NOT NULL,
    unionid       TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    last_login_at TEXT NOT NULL,
    UNIQUE (app_id, openid),
    UNIQUE (account_id, app_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS cloud_engineering_projects (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL,
    project_id    TEXT NOT NULL,
    project_code  TEXT NOT NULL DEFAULT '',
    project_name  TEXT NOT NULL DEFAULT '',
    snapshot_id   TEXT NOT NULL DEFAULT '',
    revision      INTEGER NOT NULL DEFAULT 0,
    desktop_machine_id TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE (account_id, project_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS project_members (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    project_owner_account_id INTEGER NOT NULL,
    project_id               TEXT NOT NULL,
    member_account_id        INTEGER NOT NULL,
    role                     TEXT NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'active',
    invited_by_account_id    INTEGER NOT NULL DEFAULT 0,
    joined_at                TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    removed_at               TEXT NOT NULL DEFAULT '',
    removed_by_account_id    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (project_owner_account_id, project_id, member_account_id),
    CHECK (role IN ('owner', 'admin', 'capturer', 'viewer')),
    CHECK (status IN ('active', 'removed')),
    CHECK (role != 'owner' OR member_account_id = project_owner_account_id),
    FOREIGN KEY (project_owner_account_id, project_id)
        REFERENCES cloud_engineering_projects(account_id, project_id),
    FOREIGN KEY (member_account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS project_join_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invitation_id INTEGER NOT NULL,
    project_owner_account_id INTEGER NOT NULL,
    project_id TEXT NOT NULL,
    applicant_account_id INTEGER NOT NULL,
    approver_account_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT '',
    decided_by_account_id INTEGER NOT NULL DEFAULT 0,
    decision_reason TEXT NOT NULL DEFAULT '',
    UNIQUE(invitation_id, applicant_account_id),
    FOREIGN KEY(invitation_id) REFERENCES project_invitations(id),
    FOREIGN KEY(applicant_account_id) REFERENCES accounts(id)
);
CREATE INDEX IF NOT EXISTS idx_join_requests_applicant ON project_join_requests(applicant_account_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_join_requests_approver ON project_join_requests(approver_account_id, status, id DESC);
CREATE INDEX IF NOT EXISTS idx_join_requests_project ON project_join_requests(project_owner_account_id, project_id, status, id DESC);

CREATE TABLE IF NOT EXISTS project_invitations (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    project_owner_account_id INTEGER NOT NULL,
    project_id               TEXT NOT NULL,
    invite_code_hash         TEXT UNIQUE NOT NULL,
    role                     TEXT NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'pending',
    created_by_account_id    INTEGER NOT NULL,
    accepted_by_account_id   INTEGER NOT NULL DEFAULT 0,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    expires_at               TEXT NOT NULL,
    accepted_at              TEXT NOT NULL DEFAULT '',
    revoked_at               TEXT NOT NULL DEFAULT '',
    CHECK (role IN ('admin', 'capturer', 'viewer')),
    CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
    FOREIGN KEY (project_owner_account_id, project_id)
        REFERENCES cloud_engineering_projects(account_id, project_id),
    FOREIGN KEY (created_by_account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS cloud_units (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL,
    project_id    TEXT NOT NULL,
    scope         TEXT NOT NULL DEFAULT 'engineering',
    node_code     TEXT NOT NULL,
    parent_code   TEXT NOT NULL DEFAULT '',
    node_type     TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    active        INTEGER NOT NULL DEFAULT 1,
    updated_at    TEXT NOT NULL,
    UNIQUE (account_id, project_id, scope, node_code),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS cloud_project_requirements (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id           INTEGER NOT NULL,
    project_id           TEXT NOT NULL,
    template_code        TEXT NOT NULL,
    industry             TEXT NOT NULL DEFAULT '',
    project_type         TEXT NOT NULL DEFAULT '',
    phase                TEXT NOT NULL DEFAULT '',
    division             TEXT NOT NULL DEFAULT '',
    subdivision          TEXT NOT NULL DEFAULT '',
    item                 TEXT NOT NULL DEFAULT '',
    process              TEXT NOT NULL DEFAULT '',
    requirement_name     TEXT NOT NULL DEFAULT '',
    required_type        TEXT NOT NULL DEFAULT 'recommended',
    condition_text       TEXT NOT NULL DEFAULT '',
    min_photo_count      INTEGER NOT NULL DEFAULT 1,
    recommended_count    INTEGER NOT NULL DEFAULT 1,
    shot_types           TEXT NOT NULL DEFAULT '',
    timing               TEXT NOT NULL DEFAULT '',
    before_concealment   INTEGER NOT NULL DEFAULT 0,
    gps_required         INTEGER NOT NULL DEFAULT 0,
    exif_required        INTEGER NOT NULL DEFAULT 1,
    description_template TEXT NOT NULL DEFAULT '',
    standard_source      TEXT NOT NULL DEFAULT '',
    template_version     TEXT NOT NULL DEFAULT 'V1.0',
    active               INTEGER NOT NULL DEFAULT 1,
    updated_at           TEXT NOT NULL,
    UNIQUE (account_id, project_id, template_code),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS mobile_batches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL,
    client_batch_id TEXT NOT NULL,
    project_owner_account_id INTEGER NOT NULL DEFAULT 0,
    project_id      TEXT NOT NULL,
    scope           TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT '',
    mode            TEXT NOT NULL,
    transfer_profile TEXT NOT NULL DEFAULT '',
    assignment_json TEXT NOT NULL DEFAULT '{}',
    requirement_code TEXT NOT NULL DEFAULT '',
    requirement_name TEXT NOT NULL DEFAULT '',
    target_machine_id TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'local_ready',
    error_code      TEXT NOT NULL DEFAULT '',
    error_message   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    committed_at    TEXT NOT NULL DEFAULT '',
    UNIQUE (account_id, client_batch_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS cloud_photos (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id           INTEGER NOT NULL,
    batch_id             INTEGER,
    photo_uuid           TEXT NOT NULL,
    project_owner_account_id INTEGER NOT NULL DEFAULT 0,
    project_id           TEXT NOT NULL,
    source               TEXT NOT NULL DEFAULT 'mobile',
    scope                TEXT NOT NULL,
    category             TEXT NOT NULL DEFAULT '',
    assignment_json      TEXT NOT NULL DEFAULT '{}',
    requirement_code     TEXT NOT NULL DEFAULT '',
    requirement_name     TEXT NOT NULL DEFAULT '',
    title                TEXT NOT NULL DEFAULT '',
    photo_date           TEXT NOT NULL DEFAULT '',
    photographer         TEXT NOT NULL DEFAULT '',
    photographer_account_id INTEGER NOT NULL DEFAULT 0,
    uploaded_by          TEXT NOT NULL DEFAULT '',
    uploaded_by_account_id INTEGER NOT NULL DEFAULT 0,
    capture_source       TEXT NOT NULL DEFAULT '',
    client_captured_at   TEXT NOT NULL DEFAULT '',
    orientation          INTEGER NOT NULL DEFAULT 1,
    width                INTEGER NOT NULL DEFAULT 0,
    height               INTEGER NOT NULL DEFAULT 0,
    original_filename    TEXT NOT NULL DEFAULT '',
    sha256               TEXT NOT NULL,
    size_bytes           INTEGER NOT NULL,
    mime_type            TEXT NOT NULL DEFAULT 'image/jpeg',
    storage_key          TEXT NOT NULL,
    original_sha256      TEXT NOT NULL DEFAULT '',
    original_size_bytes  INTEGER NOT NULL DEFAULT 0,
    original_mime_type   TEXT NOT NULL DEFAULT '',
    original_storage_key TEXT NOT NULL DEFAULT '',
    preview_sha256       TEXT NOT NULL DEFAULT '',
    preview_size_bytes   INTEGER NOT NULL DEFAULT 0,
    preview_width        INTEGER NOT NULL DEFAULT 0,
    preview_height       INTEGER NOT NULL DEFAULT 0,
    preview_quality      INTEGER NOT NULL DEFAULT 0,
    preview_storage_key  TEXT NOT NULL DEFAULT '',
    target_machine_id    TEXT NOT NULL DEFAULT '',
    original_cleanup_status TEXT NOT NULL DEFAULT '',
    original_cleanup_error  TEXT NOT NULL DEFAULT '',
    original_deleted_at     TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'server_saved',
    match_json           TEXT NOT NULL DEFAULT '{}',
    error_code           TEXT NOT NULL DEFAULT '',
    error_message        TEXT NOT NULL DEFAULT '',
    local_project_code   TEXT NOT NULL DEFAULT '',
    local_photo_id       TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    desktop_imported_at  TEXT NOT NULL DEFAULT '',
    deleted_at           TEXT NOT NULL DEFAULT '',
    deleted_by_machine_id TEXT NOT NULL DEFAULT '',
    deleted_by_account_id INTEGER NOT NULL DEFAULT 0,
    UNIQUE (account_id, photo_uuid),
    UNIQUE (storage_key),
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (batch_id) REFERENCES mobile_batches(id)
);

CREATE TABLE IF NOT EXISTS mobile_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL,
    batch_id    INTEGER,
    photo_uuid  TEXT NOT NULL DEFAULT '',
    job_type    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    result_json TEXT NOT NULL DEFAULT '{}',
    error_code  TEXT NOT NULL DEFAULT '',
    error_text  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (batch_id) REFERENCES mobile_batches(id)
);

CREATE TABLE IF NOT EXISTS desktop_sync_cursors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id       INTEGER NOT NULL,
    client_id        TEXT NOT NULL DEFAULT 'default',
    inbox_cursor     INTEGER NOT NULL DEFAULT 0,
    snapshot_id      TEXT NOT NULL DEFAULT '',
    snapshot_revision INTEGER NOT NULL DEFAULT 0,
    updated_at       TEXT NOT NULL,
    UNIQUE (account_id, client_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS mobile_upload_sessions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id        INTEGER NOT NULL,
    batch_id          INTEGER NOT NULL,
    photo_uuid        TEXT NOT NULL,
    project_owner_account_id INTEGER NOT NULL DEFAULT 0,
    project_id        TEXT NOT NULL,
    target_machine_id TEXT NOT NULL,
    original_sha256   TEXT NOT NULL,
    total_size_bytes  INTEGER NOT NULL,
    chunk_size_bytes  INTEGER NOT NULL,
    total_chunks      INTEGER NOT NULL,
    original_filename TEXT NOT NULL DEFAULT '',
    metadata_json     TEXT NOT NULL DEFAULT '{}',
    status            TEXT NOT NULL DEFAULT 'active',
    error_code        TEXT NOT NULL DEFAULT '',
    error_message     TEXT NOT NULL DEFAULT '',
    cleanup_status    TEXT NOT NULL DEFAULT '',
    cleanup_error     TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    expires_at        TEXT NOT NULL,
    completed_at      TEXT NOT NULL DEFAULT '',
    UNIQUE (account_id, photo_uuid),
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (batch_id) REFERENCES mobile_batches(id)
);

CREATE TABLE IF NOT EXISTS mobile_upload_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (session_id, chunk_index),
    FOREIGN KEY (session_id) REFERENCES mobile_upload_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mobile_projects_account
ON cloud_engineering_projects(account_id, active, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_project_members_account
ON project_members(member_account_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_project_members_project
ON project_members(project_owner_account_id, project_id, status, role);

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_members_one_owner
ON project_members(project_owner_account_id, project_id)
WHERE role = 'owner' AND status = 'active';

CREATE INDEX IF NOT EXISTS idx_project_invitations_project
ON project_invitations(project_owner_account_id, project_id, status, id DESC);

CREATE INDEX IF NOT EXISTS idx_project_invitations_expiry
ON project_invitations(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_mobile_units_tree
ON cloud_units(account_id, project_id, scope, active, sort_order, id);

CREATE INDEX IF NOT EXISTS idx_cloud_project_requirements
ON cloud_project_requirements(account_id, project_id, active, required_type, id);

CREATE INDEX IF NOT EXISTS idx_mobile_batches_account
ON mobile_batches(account_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_cloud_photos_gallery
ON cloud_photos(account_id, project_id, scope, category, id DESC);

CREATE INDEX IF NOT EXISTS idx_cloud_photos_inbox
ON cloud_photos(account_id, status, id);

CREATE INDEX IF NOT EXISTS idx_mobile_jobs_account
ON mobile_jobs(account_id, status, id);

CREATE INDEX IF NOT EXISTS idx_mobile_jobs_recovery
ON mobile_jobs(job_type, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_mobile_upload_sessions_quota
ON mobile_upload_sessions(account_id, status, expires_at);

CREATE INDEX IF NOT EXISTS idx_mobile_upload_chunks_session
ON mobile_upload_chunks(session_id, chunk_index);
"""

# 老库升级：accounts 表缺少的新列，启动时补上
ACCOUNTS_EXTRA_COLUMNS = {
    "invite_code": "TEXT",
    "inviter_id": "INTEGER DEFAULT 0",
    "invite_reward_months": "INTEGER DEFAULT 0",
    "email": "TEXT DEFAULT ''",
    "mobile_auth_version": "INTEGER NOT NULL DEFAULT 0",
}

INVITES_EXTRA_COLUMNS = {
    "status": "TEXT DEFAULT 'pending'",
    "qualified_at": "TEXT DEFAULT ''",
    "device_hash": "TEXT DEFAULT ''",
    "ip_hash": "TEXT DEFAULT ''",
}

MOBILE_EXTRA_COLUMNS = {
    "cloud_engineering_projects": {
        "desktop_machine_id": "TEXT NOT NULL DEFAULT ''",
    },
    "mobile_batches": {
        "project_owner_account_id": "INTEGER NOT NULL DEFAULT 0",
        "target_machine_id": "TEXT NOT NULL DEFAULT ''",
        "transfer_profile": "TEXT NOT NULL DEFAULT ''",
        "requirement_code": "TEXT NOT NULL DEFAULT ''",
        "requirement_name": "TEXT NOT NULL DEFAULT ''",
    },
    "cloud_photos": {
        "project_owner_account_id": "INTEGER NOT NULL DEFAULT 0",
        "photographer": "TEXT NOT NULL DEFAULT ''",
        "photographer_account_id": "INTEGER NOT NULL DEFAULT 0",
        "uploaded_by": "TEXT NOT NULL DEFAULT ''",
        "uploaded_by_account_id": "INTEGER NOT NULL DEFAULT 0",
        "capture_source": "TEXT NOT NULL DEFAULT ''",
        "deleted_at": "TEXT NOT NULL DEFAULT ''",
        "deleted_by_machine_id": "TEXT NOT NULL DEFAULT ''",
        "deleted_by_account_id": "INTEGER NOT NULL DEFAULT 0",
        "original_sha256": "TEXT NOT NULL DEFAULT ''",
        "original_size_bytes": "INTEGER NOT NULL DEFAULT 0",
        "original_mime_type": "TEXT NOT NULL DEFAULT ''",
        "original_storage_key": "TEXT NOT NULL DEFAULT ''",
        "preview_sha256": "TEXT NOT NULL DEFAULT ''",
        "preview_size_bytes": "INTEGER NOT NULL DEFAULT 0",
        "preview_width": "INTEGER NOT NULL DEFAULT 0",
        "preview_height": "INTEGER NOT NULL DEFAULT 0",
        "preview_quality": "INTEGER NOT NULL DEFAULT 0",
        "preview_storage_key": "TEXT NOT NULL DEFAULT ''",
        "target_machine_id": "TEXT NOT NULL DEFAULT ''",
        "original_cleanup_status": "TEXT NOT NULL DEFAULT ''",
        "original_cleanup_error": "TEXT NOT NULL DEFAULT ''",
        "original_deleted_at": "TEXT NOT NULL DEFAULT ''",
        "requirement_code": "TEXT NOT NULL DEFAULT ''",
        "requirement_name": "TEXT NOT NULL DEFAULT ''",
    },
    "mobile_upload_sessions": {
        "project_owner_account_id": "INTEGER NOT NULL DEFAULT 0",
        "cleanup_status": "TEXT NOT NULL DEFAULT ''",
        "cleanup_error": "TEXT NOT NULL DEFAULT ''",
    },
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
        for table, additions in MOBILE_EXTRA_COLUMNS.items():
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            if not table_exists:
                continue
            table_columns = {
                row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')
            }
            for name, decl in additions.items():
                if name not in table_columns:
                    conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {decl}')

        # V1.3 共享工程继续把这些表的 account_id 解释为“上传者账号”。
        # project_owner_account_id 是工程资料边界；旧数据原本由本账号独占，
        # 因此可无损回填为 account_id，既不复制照片也不改变任何现有主键。
        for table in ("mobile_batches", "cloud_photos", "mobile_upload_sessions"):
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone():
                conn.execute(
                    f'UPDATE "{table}" SET project_owner_account_id = account_id '
                    "WHERE COALESCE(project_owner_account_id, 0) <= 0"
                )

        # 每个既有工程补一条负责人关系。重复迁移只会恢复负责人关系，
        # 不会删除、覆盖或隐式加入其它成员。
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'project_members'"
        ).fetchone():
            conn.execute(
                "INSERT INTO project_members "
                "(project_owner_account_id, project_id, member_account_id, role, status, "
                "invited_by_account_id, joined_at, updated_at, removed_at, "
                "removed_by_account_id) "
                "SELECT account_id, project_id, account_id, 'owner', 'active', account_id, "
                "COALESCE(NULLIF(created_at, ''), datetime('now')), "
                "COALESCE(NULLIF(updated_at, ''), datetime('now')), '', 0 "
                "FROM cloud_engineering_projects WHERE 1 "
                "ON CONFLICT(project_owner_account_id, project_id, member_account_id) "
                "DO UPDATE SET role = 'owner', status = 'active', removed_at = '', "
                "removed_by_account_id = 0, updated_at = excluded.updated_at"
            )

        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cloud_photos'"
        ).fetchone():
            conn.execute(
                "UPDATE cloud_photos SET uploaded_by_account_id = account_id "
                "WHERE COALESCE(uploaded_by_account_id, 0) <= 0"
            )
            conn.execute(
                "UPDATE cloud_photos SET photographer_account_id = account_id "
                "WHERE source = 'mobile' AND photographer != '' "
                "AND COALESCE(photographer_account_id, 0) <= 0"
            )
            conn.execute(
                "UPDATE cloud_photos SET capture_source = CASE "
                "WHEN source = 'desktop' THEN 'desktop' ELSE '' END "
                "WHERE capture_source = '' AND source = 'desktop'"
            )
            duplicate_shared_photo_ids = conn.execute(
                "SELECT project_owner_account_id, photo_uuid, COUNT(*) AS total "
                "FROM cloud_photos GROUP BY project_owner_account_id, photo_uuid "
                "HAVING COUNT(*) > 1 LIMIT 10"
            ).fetchall()
            if duplicate_shared_photo_ids:
                details = ", ".join(
                    f"owner={row['project_owner_account_id']},uuid={row['photo_uuid']}"
                    f"({row['total']}条)"
                    for row in duplicate_shared_photo_ids
                )
                raise RuntimeError(
                    "检测到共享工程范围内重复 photo_uuid，拒绝静默迁移；"
                    f"请先备份并人工处理：{details}"
                )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_cloud_photos_shared_uuid "
                "ON cloud_photos(project_owner_account_id, photo_uuid)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cloud_photos_shared_gallery "
                "ON cloud_photos(project_owner_account_id, project_id, deleted_at, id DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cloud_photos_shared_inbox "
                "ON cloud_photos(project_owner_account_id, target_machine_id, status, id)"
            )
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mobile_batches'"
        ).fetchone():
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mobile_batches_shared_project "
                "ON mobile_batches(project_owner_account_id, project_id, account_id, id DESC)"
            )
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'mobile_upload_sessions'"
        ).fetchone():
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mobile_upload_sessions_shared_project "
                "ON mobile_upload_sessions(project_owner_account_id, project_id, account_id, id)"
            )

        duplicate_wechat_accounts = conn.execute(
            "SELECT account_id, COUNT(*) AS total FROM wechat_bindings "
            "GROUP BY account_id HAVING COUNT(*) > 1"
        ).fetchall()
        if duplicate_wechat_accounts:
            details = ", ".join(
                f"account_id={row['account_id']}({row['total']}条)"
                for row in duplicate_wechat_accounts
            )
            raise RuntimeError(
                "检测到同一桌面账号绑定多个微信，拒绝静默迁移；"
                f"请先备份并人工处理：{details}"
            )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_wechat_bindings_one_account "
            "ON wechat_bindings(account_id)"
        )

        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'mobile_upload_sessions'"
        ).fetchone():
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mobile_upload_sessions_cleanup "
                "ON mobile_upload_sessions(cleanup_status, id)"
            )

        # v1 旧行中的 sha/size/storage_key 本来就是云端小图。迁移后把它们标为
        # preview；移动来源旧行使用 legacy_shared，电脑回执时绝不能删除这唯一副本。
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cloud_photos'"
        ).fetchone():
            conn.execute(
                "UPDATE cloud_photos SET preview_sha256 = sha256 "
                "WHERE preview_sha256 = ''"
            )
            conn.execute(
                "UPDATE cloud_photos SET preview_size_bytes = size_bytes "
                "WHERE preview_size_bytes = 0"
            )
            conn.execute(
                "UPDATE cloud_photos SET preview_storage_key = storage_key "
                "WHERE preview_storage_key = ''"
            )
            conn.execute(
                "UPDATE cloud_photos SET preview_width = width, preview_height = height "
                "WHERE preview_width = 0 OR preview_height = 0"
            )
            conn.execute(
                "UPDATE cloud_photos SET original_sha256 = sha256, "
                "original_size_bytes = size_bytes, original_mime_type = mime_type, "
                "original_storage_key = storage_key, original_cleanup_status = 'legacy_shared' "
                "WHERE source = 'mobile' AND original_sha256 = ''"
            )
            conn.execute(
                "UPDATE cloud_photos SET original_cleanup_status = 'not_applicable' "
                "WHERE source = 'desktop' AND original_cleanup_status = ''"
            )
            conn.execute("DROP INDEX IF EXISTS idx_cloud_photos_inbox")
            conn.execute(
                "CREATE INDEX idx_cloud_photos_inbox ON cloud_photos "
                "(account_id, target_machine_id, status, id)"
            )
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
        conn.executescript(MOBILE_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    migrate()
    conn = connect()
    try:
        # Lifetime consumption survives photo deletion; seed historical mobile uploads.
        conn.execute("INSERT OR IGNORE INTO mobile_upload_usage "
                     "(project_owner_account_id,photo_uuid,project_id,created_at) "
                     "SELECT project_owner_account_id,photo_uuid,project_id,created_at "
                     "FROM cloud_photos WHERE source='mobile'")
        conn.commit()
    finally:
        conn.close()
