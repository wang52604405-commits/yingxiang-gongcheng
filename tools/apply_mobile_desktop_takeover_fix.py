from __future__ import annotations

import ast
from pathlib import Path

SERVER = Path("server/mobile_api.py")
TESTS = Path("tests/test_mobile_server.py")

source = SERVER.read_text(encoding="utf-8")
old = '''            existing_archive_machine = _machine_id(
                existing["desktop_machine_id"] if existing else ""
            )
            if (
                existing_archive_machine
                and existing_archive_machine != desktop_machine_id
            ):
                raise ApiProblem(
                    "project_archive_machine_conflict",
                    "该工程已绑定另一台归档电脑，请先在原电脑解除绑定",
                    409,
                )
'''
new = '''            existing_archive_machine = _machine_id(
                existing["desktop_machine_id"] if existing else ""
            )
            retargeted_pending_count = 0
            if (
                existing_archive_machine
                and existing_archive_machine != desktop_machine_id
            ):
                # A replacement/second bound desktop may safely take over a real named
                # project only when there is undelivered mobile work for the old archive
                # machine and the new desktop proves it has the same current project tree.
                # Imported or deleted photos are never replayed.
                pending_rows = conn.execute(
                    "SELECT id, scope, assignment_json FROM cloud_photos "
                    "WHERE project_owner_account_id = ? AND project_id = ? "
                    "AND source = 'mobile' AND status = 'desktop_pending' "
                    "AND deleted_at = '' AND target_machine_id = ? ORDER BY id",
                    (current["id"], project_id, existing_archive_machine),
                ).fetchall()
                existing_project_code = _safe_text(
                    existing["project_code"] if existing else "", 100
                )
                incoming_units = {
                    str(node.get("node_code") or "").strip()
                    for node in nodes
                    if node.get("scope") == "engineering"
                    and node.get("node_type") == "unit"
                }
                incoming_processes = {
                    (
                        str(node.get("parent_code") or "").strip(),
                        str(node.get("name") or "").strip(),
                    )
                    for node in nodes
                    if node.get("scope") == "engineering"
                    and node.get("node_type") == "process"
                }
                incoming_other_nodes = {
                    str(node.get("node_code") or "").strip()
                    for node in nodes
                    if node.get("scope") == "other"
                }
                takeover_allowed = bool(
                    project_id != "default"
                    and existing_project_code
                    and existing_project_code == project_code
                    and pending_rows
                )
                if takeover_allowed:
                    for pending in pending_rows:
                        assignment = _json(pending["assignment_json"], {})
                        if pending["scope"] == "engineering":
                            unit_code = _safe_text(assignment.get("unit_code"), 160)
                            process_name = _safe_text(assignment.get("process_name"), 160)
                            if not unit_code or unit_code not in incoming_units:
                                takeover_allowed = False
                                break
                            if process_name and (unit_code, process_name) not in incoming_processes:
                                takeover_allowed = False
                                break
                        elif pending["scope"] == "other":
                            other_code = _safe_text(assignment.get("other_node_code"), 160)
                            if not other_code or other_code not in incoming_other_nodes:
                                takeover_allowed = False
                                break
                        else:
                            takeover_allowed = False
                            break
                if not takeover_allowed:
                    raise ApiProblem(
                        "project_archive_machine_conflict",
                        "该工程已绑定另一台归档电脑；只有新电脑持有同一完整工程且服务器存在待归档照片时才可安全接管",
                        409,
                    )

                takeover_timestamp = now()
                # Retarget every not-yet-imported mobile object for this project, including
                # an upload that was already in flight when the desktop changed.  The
                # already-imported/deleted rows stay frozen on their original machine.
                conn.execute(
                    "UPDATE cloud_photos SET target_machine_id = ?, updated_at = ? "
                    "WHERE project_owner_account_id = ? AND project_id = ? "
                    "AND source = 'mobile' AND deleted_at = '' "
                    "AND status <> 'desktop_imported' AND target_machine_id = ?",
                    (
                        desktop_machine_id,
                        takeover_timestamp,
                        current["id"],
                        project_id,
                        existing_archive_machine,
                    ),
                )
                conn.execute(
                    "UPDATE mobile_batches SET target_machine_id = ?, updated_at = ? "
                    "WHERE project_owner_account_id = ? AND project_id = ? "
                    "AND status <> 'desktop_imported' AND target_machine_id = ?",
                    (
                        desktop_machine_id,
                        takeover_timestamp,
                        current["id"],
                        project_id,
                        existing_archive_machine,
                    ),
                )
                conn.execute(
                    "UPDATE mobile_upload_sessions SET target_machine_id = ?, updated_at = ? "
                    "WHERE project_owner_account_id = ? AND project_id = ? "
                    "AND status IN ('active', 'finalizing') AND target_machine_id = ?",
                    (
                        desktop_machine_id,
                        takeover_timestamp,
                        current["id"],
                        project_id,
                        existing_archive_machine,
                    ),
                )
                retargeted_pending_count = len(pending_rows)
'''
if source.count(old) != 1:
    raise SystemExit(f"project snapshot conflict anchor count={source.count(old)}")
source = source.replace(old, new, 1)
response_anchor = '''                    "requirement_count": requirement_count,
'''
response_new = '''                    "requirement_count": requirement_count,
                    "retargeted_pending_count": retargeted_pending_count,
'''
if source.count(response_anchor) < 1:
    raise SystemExit("snapshot response anchor missing")
# The first requirement_count in this route response is the intended one.
route_pos = source.index('def desktop_project_snapshot():')
response_pos = source.index(response_anchor, route_pos)
source = source[:response_pos] + source[response_pos:].replace(response_anchor, response_new, 1)
SERVER.write_text(source, encoding="utf-8")

text = TESTS.read_text(encoding="utf-8")
method_name = "test_pending_mobile_photos_follow_verified_project_takeover"
if method_name not in text:
    tree = ast.parse(text)
    target = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MobileServerContractTest"
    )
    method = r'''

    def test_pending_mobile_photos_follow_verified_project_takeover(self):
        project_id = "takeover-" + uuid.uuid4().hex[:12]
        self._snapshot(
            self.token_a,
            "归档电脑接管测试工程",
            project_id=project_id,
            revision=100,
        )

        imported_batch = self._create_batch(self.token_a, project_id=project_id)
        imported_uuid = str(uuid.uuid4())
        uploaded = self._upload(
            self.token_a,
            imported_batch,
            imported_uuid,
            self._jpeg((45, 75, 105)),
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        committed = self.client.post(
            f"/api/mobile/v1/batches/{imported_batch}/commit",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(committed.status_code, 200, committed.get_json())
        acked = self.client.post(
            f"/api/desktop/v1/photos/{imported_uuid}/ack",
            json={
                "local_project_code": "LOCAL-IMPORTED",
                "local_photo_id": "IMPORTED-SY001",
                "desktop_machine_id": "MACHINE-A",
            },
            headers=self._headers(self.desktop_token_a),
        )
        self.assertEqual(acked.status_code, 200, acked.get_json())

        pending_batch = self._create_batch(self.token_a, project_id=project_id)
        pending_uuid = str(uuid.uuid4())
        uploaded = self._upload(
            self.token_a,
            pending_batch,
            pending_uuid,
            self._jpeg((55, 85, 115)),
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        committed = self.client.post(
            f"/api/mobile/v1/batches/{pending_batch}/commit",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(committed.status_code, 200, committed.get_json())

        switched = self._snapshot(
            self.token_a,
            "归档电脑接管测试工程",
            project_id=project_id,
            desktop_machine_id="MACHINE-A-ALT",
            revision=101,
        )
        self.assertEqual(switched.status_code, 200, switched.get_json())
        self.assertEqual(switched.get_json()["retargeted_pending_count"], 1)

        conn = self.db.connect()
        try:
            imported = conn.execute(
                "SELECT status,target_machine_id FROM cloud_photos WHERE photo_uuid=?",
                (imported_uuid,),
            ).fetchone()
            pending = conn.execute(
                "SELECT status,target_machine_id FROM cloud_photos WHERE photo_uuid=?",
                (pending_uuid,),
            ).fetchone()
            batch = conn.execute(
                "SELECT status,target_machine_id FROM mobile_batches WHERE id=?",
                (pending_batch,),
            ).fetchone()
            self.assertEqual(imported["status"], "desktop_imported")
            self.assertEqual(imported["target_machine_id"], "MACHINE-A")
            self.assertEqual(pending["status"], "desktop_pending")
            self.assertEqual(pending["target_machine_id"], "MACHINE-A-ALT")
            self.assertEqual(batch["target_machine_id"], "MACHINE-A-ALT")
        finally:
            conn.close()

        alt = self.client.get(
            "/api/desktop/v1/inbox?desktop_machine_id=MACHINE-A-ALT&limit=100",
            headers=self._headers(self.desktop_token_a_alt),
        )
        self.assertEqual(alt.status_code, 200, alt.get_json())
        self.assertIn(pending_uuid, {item["photo_uuid"] for item in alt.get_json()["items"]})
        old = self.client.get(
            "/api/desktop/v1/inbox?desktop_machine_id=MACHINE-A&limit=100",
            headers=self._headers(self.desktop_token_a),
        )
        self.assertEqual(old.status_code, 200, old.get_json())
        self.assertNotIn(pending_uuid, {item["photo_uuid"] for item in old.get_json()["items"]})
'''
    lines = text.splitlines(keepends=True)
    insert_at = target.end_lineno
    lines[insert_at:insert_at] = [method]
    text = "".join(lines)
    TESTS.write_text(text, encoding="utf-8")

# Parse both files before allowing CI to run.
ast.parse(SERVER.read_text(encoding="utf-8"))
ast.parse(TESTS.read_text(encoding="utf-8"))
print("mobile desktop takeover patch applied")
