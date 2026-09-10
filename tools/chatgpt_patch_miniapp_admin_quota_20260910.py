from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, got {count}\n---OLD---\n{old[:500]}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "server/mobile_api.py",
    'raw_limit = _product_config(conn).get("mini_program", {}).get("free_upload_limit", 100)',
    'raw_limit = _product_config(conn).get("mini_program", {}).get("free_upload_limit", 500)',
)

replace_once(
    "server/mobile_api.py",
    '''        can_review = False
        if int(actor_id) in {int(item["approver_account_id"]), int(item["project_owner_account_id"])} and int(actor_id) != int(item["applicant_account_id"]):
            try:
                project_for(conn, actor_id, _project_ref(item["project_owner_account_id"], item["project_id"]), MANAGE_MEMBER_ROLES)
                project_for(conn, item["approver_account_id"], _project_ref(item["project_owner_account_id"], item["project_id"]), MANAGE_MEMBER_ROLES)
                can_review = status == "pending"
            except ApiProblem:
                pass
''',
    '''        can_review = False
        # 负责人和当前任一管理员都能审核待加入申请；申请人本人永远不能审核自己。
        # 原分享人仍须保有管理权限，避免已被降权/移除的旧邀请继续产生有效审批链。
        if int(actor_id) != int(item["applicant_account_id"]):
            try:
                project_for(conn, actor_id, _project_ref(item["project_owner_account_id"], item["project_id"]), MANAGE_MEMBER_ROLES)
                project_for(conn, item["approver_account_id"], _project_ref(item["project_owner_account_id"], item["project_id"]), MANAGE_MEMBER_ROLES)
                can_review = status == "pending"
            except ApiProblem:
                pass
''',
)

replace_once(
    "server/mobile_api.py",
    '''    @blueprint.get("/api/mobile/v1/project-join-requests")
    def list_project_join_requests():
        current = user()
        conn = db.connect()
        try:
            reference = str(request.args.get("project_id") or "")
            rows = conn.execute("SELECT * FROM project_join_requests WHERE applicant_account_id = ? OR approver_account_id = ? OR project_owner_account_id = ? ORDER BY id DESC", (current["id"], current["id"], current["id"])).fetchall()
            visible = []
''',
    '''    @blueprint.get("/api/mobile/v1/project-join-requests")
    def list_project_join_requests():
        current = user()
        conn = db.connect()
        try:
            reference = str(request.args.get("project_id") or "")
            if reference:
                # 项目成员页/首页徽标按项目读取：负责人和任一管理员都能看到该项目的申请。
                managed_project = project_for(conn, current["id"], reference, MANAGE_MEMBER_ROLES)
                rows = conn.execute(
                    "SELECT * FROM project_join_requests WHERE project_owner_account_id = ? "
                    "AND project_id = ? ORDER BY id DESC",
                    (managed_project["account_id"], managed_project["project_id"]),
                ).fetchall()
            else:
                # 无 project_id 时兼容申请人自己的状态页，以及旧版分享人/负责人读取方式。
                rows = conn.execute("SELECT * FROM project_join_requests WHERE applicant_account_id = ? OR approver_account_id = ? OR project_owner_account_id = ? ORDER BY id DESC", (current["id"], current["id"], current["id"])).fetchall()
            visible = []
''',
)

replace_once(
    "server/mobile_api.py",
    '''            if not row or int(current["id"]) not in {int(row["approver_account_id"]), int(row["project_owner_account_id"])} or int(current["id"]) == int(row["applicant_account_id"]):
                raise ApiProblem("join_request_not_found", "申请不存在或无权审批", 404)
''',
    '''            if not row or int(current["id"]) == int(row["applicant_account_id"]):
                raise ApiProblem("join_request_not_found", "申请不存在或无权审批", 404)
''',
)

replace_once(
    "server/app.py",
    '''    raw_limit = mini_program.get("free_upload_limit", 100)
    mini_program["free_upload_limit"] = max(0, min(100000, int(100 if raw_limit is None else raw_limit)))
''',
    '''    raw_limit = mini_program.get("free_upload_limit", 500)
    parsed_limit = int(500 if raw_limit is None else raw_limit)
    # 100 是旧版本的小程序默认额度；产品策略升级后自动迁移为 500。
    # 0 和其它管理员明确设置的数值仍保持原意。
    if parsed_limit == 100:
        parsed_limit = 500
    mini_program["free_upload_limit"] = max(0, min(100000, parsed_limit))
''',
)

replace_once(
    "tests/test_product_core.py",
    '''        product = _normalized_product_config({"mini_program": {"free_upload_limit": 100}})
        self.assertEqual(product["mini_program"]["free_upload_limit"], 100)
''',
    '''        product = _normalized_product_config({"mini_program": {"free_upload_limit": 100}})
        self.assertEqual(product["mini_program"]["free_upload_limit"], 500)
''',
)

replace_once(
    "tests/test_product_core.py",
    '''        self.assertEqual(product["mini_program"]["free_upload_limit"], 100)
''',
    '''        self.assertEqual(product["mini_program"]["free_upload_limit"], 500)
''',
)

print("one-time patch applied")
