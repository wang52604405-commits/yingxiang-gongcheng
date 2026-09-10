from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, got {count}\n---OLD---\n{old[:700]}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "server/mobile_api.py",
    '''    except (TypeError, ValueError):
        limit = 100
    used = int(conn.execute(
''',
    '''    except (TypeError, ValueError):
        limit = 500
    used = int(conn.execute(
''',
)

replace_once(
    "tests/test_mobile_server.py",
    '''    def test_join_approval_blocks_old_client_expired_requests_and_unrelated_admin(self):
        snapshot, invite = self._wechat_join_invite()
        old = self.client.post("/api/mobile/v1/project-invites/join", json={"code": invite}, headers=self._headers(self.token_b))
        self.assertEqual(old.status_code, 400, old.get_json())
        bad_phone = self._wechat_join(invite, uuid.uuid4().hex, phone="123")
        self.assertEqual(bad_phone.status_code, 400)
        pending = self._wechat_join(invite, uuid.uuid4().hex).get_json()
        rid = pending["join_request"]["id"]
        conn = self.db.connect()
        try:
            member = conn.execute("SELECT id FROM accounts WHERE username = 'tenant_b'").fetchone()["id"]
            conn.execute("INSERT INTO project_members (project_owner_account_id, project_id, member_account_id, role, joined_at, updated_at) VALUES (?, ?, ?, 'admin', '2026-01-01', '2026-01-01')", (snapshot["owner_account_id"], snapshot["project_ref"].split(":", 1)[1], member))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.client.post(f"/api/mobile/v1/project-join-requests/{rid}/approve", json={}, headers=self._headers(self.token_b)).status_code, 404)
        hidden = self.client.get(f"/api/mobile/v1/project-join-requests?project_id={snapshot['project_ref']}", headers=self._headers(self.token_b)).get_json()["requests"]
        self.assertEqual(hidden, [])
        conn = self.db.connect()
        try:
            conn.execute("UPDATE project_invitations SET expires_at = '2000-01-01' WHERE invite_code_hash = ?", (hashlib.sha256(invite.encode()).hexdigest(),))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.client.post(f"/api/mobile/v1/project-join-requests/{rid}/approve", json={}, headers=self._headers(self.token_a)).status_code, 409)
        own = self.client.get("/api/mobile/v1/project-join-requests", headers=self._headers(pending["token"])).get_json()["requests"][0]
        self.assertEqual(own["status"], "expired")
''',
    '''    def test_join_approval_allows_current_project_admin_and_blocks_expired_requests(self):
        snapshot, invite = self._wechat_join_invite()
        old = self.client.post("/api/mobile/v1/project-invites/join", json={"code": invite}, headers=self._headers(self.token_b))
        self.assertEqual(old.status_code, 400, old.get_json())
        bad_phone = self._wechat_join(invite, uuid.uuid4().hex, phone="123")
        self.assertEqual(bad_phone.status_code, 400)
        pending = self._wechat_join(invite, uuid.uuid4().hex).get_json()
        rid = pending["join_request"]["id"]
        conn = self.db.connect()
        try:
            member = conn.execute("SELECT id FROM accounts WHERE username = 'tenant_b'").fetchone()["id"]
            conn.execute("INSERT INTO project_members (project_owner_account_id, project_id, member_account_id, role, joined_at, updated_at) VALUES (?, ?, ?, 'admin', '2026-01-01', '2026-01-01')", (snapshot["owner_account_id"], snapshot["project_ref"].split(":", 1)[1], member))
            conn.commit()
        finally:
            conn.close()
        visible = self.client.get(f"/api/mobile/v1/project-join-requests?project_id={snapshot['project_ref']}", headers=self._headers(self.token_b)).get_json()["requests"]
        self.assertEqual([item["id"] for item in visible], [rid])
        self.assertTrue(visible[0]["can_review"])
        approved = self.client.post(f"/api/mobile/v1/project-join-requests/{rid}/approve", json={}, headers=self._headers(self.token_b))
        self.assertEqual(approved.status_code, 200, approved.get_json())

        expired_snapshot, expired_invite = self._wechat_join_invite()
        expired_pending = self._wechat_join(expired_invite, uuid.uuid4().hex).get_json()
        expired_rid = expired_pending["join_request"]["id"]
        conn = self.db.connect()
        try:
            conn.execute("UPDATE project_invitations SET expires_at = '2000-01-01' WHERE invite_code_hash = ?", (hashlib.sha256(expired_invite.encode()).hexdigest(),))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.client.post(f"/api/mobile/v1/project-join-requests/{expired_rid}/approve", json={}, headers=self._headers(self.token_a)).status_code, 409)
        own = self.client.get("/api/mobile/v1/project-join-requests", headers=self._headers(expired_pending["token"])).get_json()["requests"][0]
        self.assertEqual(own["status"], "expired")
''',
)

print("second one-time patch applied")
