# 工程影像移动端 API v1 契约

> 基线：`origin/main@b5a5924`（A20260822-2.64）
> 首发端：微信小程序
> 图片策略：V1.3.1 手机先安全保存 JPEG/PNG 源文件（单文件 `<= 50MiB`），在本机生成 JPEG `<= 1MiB` 归档图和 JPEG `<= 102400` 字节预览；只上传归档图，电脑确认落盘后删除云端中转归档图，手机和云端长期保留预览。旧原图/分片端点仅用于兼容已入队的旧客户端。

## 1. 通用规则

- 前缀：`/api/mobile/v1`；桌面同步前缀：`/api/desktop/v1`。
- 鉴权：`Authorization: Bearer <token>`；所有查询与写入必须按令牌中的 `account_id` 隔离。微信令牌为 `scope=mobile`，必须被全部 `/api/desktop/v1` 拒绝。
- 幂等：批次使用 `client_batch_id`，仅当工程/scope/category/mode/assignment/冻结目标机器全部一致时幂等，否则 `409 batch_id_conflict`。照片使用永久 `photo_uuid`；仅在原图 SHA-256、工程、来源和移动批次均一致时返回原资源，否则 `409 photo_uuid_conflict`。
- 隐私边界：`bootstrap`、移动图库、照片详情和批次接口只返回永久预览地址，绝不返回原图地址或对象键。原图短签名地址只由目标工程电脑的 inbox 返回。
- 时间：ISO 8601 UTC；分页：`cursor` + `limit`，响应返回 `next_cursor`。移动影像库首屏按最新照片优先，后续游标向更早照片翻页；桌面 inbox 游标仍按 ID 递增拉取。
- 成功响应至少包含 `{ "ok": true }`；错误响应包含稳定 `code`、中文 `error` 与可选 `retryable`。

## 2. 登录与启动

### `POST /api/mobile/v1/auth/account-login`

账号密码登录的第一步。请求：`{ username, password, code, app_id }`。服务器验证现有云账号、交换本次微信 `code`，成功后只返回 `{ account, binding_intent }`。`binding_intent` 是有效期 10 分钟的绑定意图凭据，不包含密码；此步骤不创建微信绑定，也不签发移动端 token。

### `POST /api/mobile/v1/auth/wechat-bind-confirm`

用户在第二步明确确认绑定当前微信后，请求：`{ binding_intent }`。服务器重新校验绑定意图、账号状态和绑定关系，成功创建或确认同一绑定后才返回 `{ token, account, bootstrap }`。同一账号与同一微信的重复确认保持幂等；冲突绑定不会被静默覆盖。

### `POST /api/mobile/v1/auth/wechat-login`

已绑定用户主动点击“微信快捷登录”时使用。请求：`{ code, app_id }`。已绑定时返回 `{ token, account, bootstrap }`；`token` 显式带 `scope=mobile`。未绑定时返回 `{ binding_required: true, binding_ticket }`，新客户端提示用户改用账号密码登录，不会在启动时静默继续绑定。

### `POST /api/mobile/v1/auth/wechat-bind`

旧版客户端兼容接口。请求：`{ binding_ticket, username, password }`。验证现有云账号后绑定 OpenID，返回 `{ token, account, bootstrap }`；服务器不保存微信 code 或明文密码。新客户端不再使用此接口完成首次绑定。

没有有效本地 token 时，新客户端直接显示账号密码登录页，不会在启动时自动发起微信快捷登录。已有有效 token 时仍先调用 `bootstrap` 校验会话；会话失效后返回登录页，由用户重新账号登录，或主动选择已绑定微信的快捷登录。登录与绑定接口复用按真实客户端 IP 的短窗限流；服务只在 127.0.0.1 后信任一层 nginx 转发头。

### `GET /api/mobile/v1/bootstrap`

返回账号、服务器时间、当前工程、工程列表、层级数量摘要、照片 `queue`、兼容分片会话 `chunk_queue`、最近上传以及当前上传契约。`upload_contract` 除旧版兼容上限外，还含 `preferred_transfer_profile=jpeg_1m`，以及该规格的 `mime_type=image/jpeg`、`max_bytes=1048576`、`direct_upload=true`；永久预览限制为 `102400` 字节，最近上传只含预览。

## 3. 工程与图库

- `GET /api/mobile/v1/projects`
- `GET /api/mobile/v1/projects/{project_id}/tree`
- `GET /api/mobile/v1/projects/{project_id}/other-tree`
- `GET /api/mobile/v1/photos?project_id=&scope=&category=&unit_code=&cursor=&limit=`：`cursor` 为空或 `0` 时返回最新一页（`id DESC`）；`next_cursor` 是本页末尾最小 ID，下一页查询 `id < cursor`，不会把新上传照片插入正在向后翻阅的旧页。
- `GET /api/mobile/v1/photos/{photo_uuid}`

`scope` 仅允许 `engineering | other`。`category` 仅允许 `construction | supervision`，且只在 `engineering` 下使用。工程归档目标为 `{ unit_code, process_name? }`；其它影像目标为 `{ other_node_code }`。

## 4. 上传批次

### `POST /api/mobile/v1/batches`

请求：

```json
{
  "client_batch_id": "uuid",
  "project_id": "default",
  "scope": "engineering",
  "category": "construction",
  "mode": "direct",
  "transfer_profile": "jpeg_1m",
  "assignment": {
    "unit_project_code": "...",
    "unit_project_name": "...",
    "part_code": "...",
    "part_name": "...",
    "unit_code": "...",
    "unit_name": "...",
    "process_name": ""
  }
}
```

`mode` 仅允许 `direct | auto`。`jpeg_1m` 新批次无论 direct/auto 都必须提交完整工程层级；工程影像必须有类别、单位工程、分部工程、单元工程，有 active 工序的单元还必须有合法工序；其它影像必须有目录。服务器把工程快照中的 `desktop_machine_id` 固化为批次 `target_machine_id`；工程未绑定 active 电脑时拒绝创建，后续工程改由其它电脑同步也不会改投旧批次。

已有远端批次缺少归档信息时，客户端调用 `PATCH /api/mobile/v1/batches/{batch_id}/archive-info`，请求 `{ "assignment": { ...完整归档字段... } }`。接口按当前成员采集权限、批次工程、工程树与状态校验，并原子更新批次及尚未投递的照片；相同内容重复调用幂等成功。

### `POST /api/mobile/v1/batches/{batch_id}/photos`

`multipart/form-data`：字段 `file`、`transfer_profile=jpeg_1m`、`photo_uuid`、`client_captured_at`、`orientation`、`sha256`（归档图）、`original_size_bytes`（兼容字段名，当前表示归档图大小）、`original_filename`、可选 `title/photo_date/width/height`。服务器以实际字节和解码尺寸为准，并校验：

1. `jpeg_1m` 单图严格不超过 `1048576` 字节并使用直传；
2. 仅接受可完整解码的静态 JPEG；旧无 transfer profile 请求仍按兼容 JPEG/PNG 契约处理；
3. 归档图像素数和最长边不超过服务器安全配置；
4. 客户端 SHA-256、可选文件大小与服务器计算一致；
5. `photo_uuid` 属于当前账号、批次冻结的目标电脑仍为 active；
6. 从最长边 1920 开始，在 JPEG 质量 30–90 间寻找最高可用质量，仍超限则每轮缩小 15%，最终预览严格 `<=102400` 字节。

归档图对象为 `accounts/{account_id}/projects/{project_id}/photos/{photo_uuid}.jpg`，永久预览为 `accounts/{account_id}/projects/{project_id}/previews/{photo_uuid}.jpg`。自动识别在提交前优先读取归档图，旧兼容行才回退预览。

### 旧版大原图分片续传（仅兼容）

服务端继续支持已由旧客户端入队的文件：总大小严格 `<=52428800` 字节，固定 `4194304` 字节分片；V1.3.1 新采集批次不再进入该流程。除最后一片外每片必须正好 4MiB，服务端按账号、批次、`photo_uuid` 和批次冻结目标电脑隔离：

- `POST /api/mobile/v1/batches/{batch_id}/chunked-uploads/init`：JSON `{ photo_uuid, sha256, original_size_bytes, original_filename, chunk_size_bytes, total_chunks, client_captured_at, orientation, width, height, title, photo_date }`。相同 UUID 仅在所有上下文和原图信息一致时幂等；否则 `409 photo_uuid_conflict`。
- `GET /api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}`：断点查询，返回 `upload.upload_id/status/total_size_bytes/chunk_size_bytes/total_chunks/uploaded_chunks/uploaded_bytes/expires_at/error`；`uploaded_chunks` 是客户端补传依据。
- `PUT /api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}/chunks/{index}`：请求体为原始分片字节，头 `X-Chunk-SHA256` 必填。同索引同哈希幂等成功，不同哈希返回 `409 chunk_conflict`；允许乱序上传。
- `POST /api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}/finalize`：JSON `{ sha256, original_size_bytes, total_chunks }`。服务端重新逐片校验并组装、校验整图 SHA、完整解码 JPEG/PNG、生成预览后才写照片记录；成功返回 `{ photo, upload }`，重复完成幂等返回已有照片。
- `POST /api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}/abort`：幂等取消并清理临时片。

分片会话有有限 TTL，并限制每账号/全局活跃会话数和预留临时字节；过期、取消、校验失败与成功完成都会回收临时片。清理状态持久化为 `pending/cleaned`；失败会由后续请求周期重试，且 `pending` 仍占会话数和预留字节配额，防止临时目录无界增长。分片响应可附带 `cleanup_status`、`cleanup_error`。批次存在 `active/finalizing` 会话时，识别和提交均返回 `409 batch_uploads_incomplete`。进程重启后客户端通过 GET 查询服务器已确认的片；过期会话重新 init 后从空集合补传。

### 其余批次接口

- `GET /api/mobile/v1/batches/{batch_id}`：返回单图状态、进度、匹配候选和错误；轮询该接口也会检查识别心跳并恢复真正超时的任务。
- `POST /api/mobile/v1/batches/{batch_id}/analyze`：快速受理 OCR/规则匹配，首次与正在运行时返回 HTTP `202` 及 `{ job, batch }`；并发重试返回同一个 job。批次已是 `needs_review` 时 HTTP `200` 幂等返回现有结果，不重复 OCR、不倒退状态。
- `GET /api/mobile/v1/jobs/{job_id}`：按账号轮询 `{ job, batch }`；job 状态为 `queued | running | completed | failed`。识别异常会把照片安全转为人工确认；新进程启动时立即把旧进程遗留的 queued/running job 恢复为 `needs_review`，运行中的 job 由独立周期心跳续租，单张 OCR 超过普通轮询间隔也不会被误判中断。
- `PATCH /api/mobile/v1/batches/{batch_id}/assignments`：逐图确认 `{ photo_uuid, unit_code/process_name/other_node_code, title, photo_date }`。
- `POST /api/mobile/v1/batches/{batch_id}/commit`：校验所有照片有合法归属后进入桌面待归档。

## 5. 桌面同步

- `POST /api/desktop/v1/project-snapshot`：顶层带 `snapshot_id`、`revision`、`desktop_machine_id`，后者必须是当前账号 `machines.active=1` 的绑定电脑；事务式上传工程根、完整单元层级、工序和其它影像树，缺失节点只标记停用。
- `GET /api/desktop/v1/inbox?desktop_machine_id=&cursor=&limit=`：机器 ID 必填且必须 active；只返回 `account_id + target_machine_id` 精确匹配的待归档照片。item 的 `download_url/original_download_url` 指向中转归档图短签名地址，并保留兼容字段 `original_sha256/original_size_bytes/original_filename/original_mime_type`；无机器或错机器均不返回下载地址。
- `POST /api/desktop/v1/photos/{photo_uuid}/ack`：请求 `{ local_project_code, local_photo_id, desktop_machine_id }`。服务器先持久化 `desktop_imported`，再删除中转归档图；删除失败仍返回成功并记录 `cleanup_pending`，相同 ACK 会重试清理。永久预览不删除。
- `POST /api/desktop/v1/backfill-photo`：`multipart` 带 active `desktop_machine_id`，只上传现有电脑照片的 JPEG `<=102400` 字节查看副本与元数据，绝不上传、转码或修改电脑本地原图。

桌面端先用 `/api/login` 令牌调用 `/api/activate {machine_id}`，使用返回的 `desktop_sync_token`（claims 含 `scope=desktop_sync,machine_id`）调用上述桌面接口。服务端同时校验 token 机器、请求机器与 `machines.active=1`。`desktop_sync_token` 仅能访问 `/api/desktop/v1`，不能访问移动、管理员或旧云预览接口。普通登录令牌与微信 token 即使知道机器 ID 也不能调用桌面 v1，均返回 403。

生产 OSS 必须拆成两个私有 Bucket：原图中转 Bucket 关闭版本控制并设短期生命周期兜底，永久预览 Bucket 开启版本控制且不自动删除；两者均启用服务端加密与最小权限 RAM 角色。普通 delete 在开启版本控制的 Bucket 中只会写删除标记，因此禁止把原图和预览放进同一个版本化 Bucket。
小程序 request/uploadFile 合法域名为 API HTTPS 域名；由于 OSS 预览使用直签 HTTPS URL，downloadFile 还必须加入「预览 Bucket 实际主机或预览自定义域名」。该主机要在正式 Bucket 创建后确认，是真机发布阻塞项；原图 Bucket 主机只供电脑使用。

## 6. 状态机

```text
local_ready -> uploading/direct(jpeg_1m) -> server_saved
旧队列兼容：uploading/chunk-active|chunk-finalizing -> server_saved
server_saved -> analyzing -> needs_review
server_saved/needs_review -> desktop_pending -> desktop_imported
desktop_imported -> 中转归档图 deleted | cleanup_pending（预览永久保留）
任一可重试阶段 -> failed -> 原阶段
```

`desktop_pending` 和 `desktop_imported` 不允许再自动识别、改归属或回退；手机重试 commit 只幂等返回当前终态。

微信退后台导致请求中断时，只回到本机待传或失败状态；再次进入前台再续传，不能显示为上传成功。
