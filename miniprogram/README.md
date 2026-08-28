# 工程影像微信小程序 V1

这是工程影像电脑软件的微信小程序客户端。界面以已确认的第二版设计为唯一基线，当前工程显示为“邯郸市永年区洺河龙泉缓洪工程”。00/10/20/30/90 是开发流程编号，不会出现在产品界面。

## 已实现

- 登录以电脑端已有账号为准：先输入账号密码，客户端同时提交本次微信 `code/app_id`；服务器第一步只返回账号与短期 `binding_intent`，不签发 token、不落微信绑定。用户在第二步明确确认绑定当前微信后，服务器才返回 `token/account/bootstrap` 并进入工作台。
- 已绑定用户可主动点击“微信快捷登录”；没有有效 token 时直接显示账号登录页，不在启动时静默微信登录。已有 token 启动时先用 `bootstrap` 验证，登录/绑定响应自带的数据会立即写入，随后再联网刷新。
- 账号、当前工程、归档位置、缓存和本机队列均按 `account.id` 隔离；切换或重新连接账号不会混看、误传或删除上一账号原图。
- 工作台、工程选择、影像库、上传、自动匹配确认、待上传、照片详情和我的。
- 底部“工作台｜影像库｜上传｜待上传｜我的”，微信端是原生 `custom-tab-bar`，中央上传按钮突出显示。
- 工程影像与其它影像严格分开；工程影像支持施工/监理，先选单元再按需显示工序。
- 原图仅接受 JPEG/PNG，单张硬上限 50MB；选择后先做大小预检，再把原始字节第一时间保存到微信用户目录并写恢复记录，不把 PNG 转成 JPEG 冒充原图。
- 本机另生成并长期保留 JPEG 预览：最长边从 1920px 开始，在质量 30–90 之间寻找最高合格质量，硬限制 `≤102400` 字节；最低质量仍超限时每轮缩边 15%。
- 微信基础库 2.25.0 及以上相册一次最多选择 20 张；旧基础库自动降级为 9 张。发布最低基础库应设置为 2.25.0。
- 生成预览前，从 JPEG 文件头的有界读取中提取 EXIF `DateTimeOriginal` / `DateTimeDigitized` 和方向 1–8；缺少 EXIF 时才回退文件时间或当前时间，不会为此把几十 MB 原图整块读进内存。
- 原图 SHA-256 使用 1MB 分块增量读取，避免大图哈希时产生约两倍内存峰值；小预览也使用同一校验逻辑。
- 160MB 容量统计包含所有尚未中转的原图和全部长期留存预览；每张复制前按“当前占用 + 原图 + 100KB 预留”检查，保存后再次硬校验。
- 上传并发固定为 2；原图不超过 8MiB 时使用 `uploadFile`，更大的原图使用 4MiB 文件分片和普通二进制请求，逐片校验、查询服务端已收索引并在回到前台后断点续传；全程不会把 50MB 原图一次读入内存。
- `client_batch_id` 与 `photo_uuid` 永久稳定；本机分片进度只作恢复线索，续传时以服务器 `uploaded_chunks` 为权威，上传会话过期后会安全补齐缺片，不会因旧进度跳片。
- 队列不再把整个账号写进一个 Storage 键：照片和批次按账号分目录、按记录双槽分片保存。复制原图前先写 WAL 清单，原图使用确定性路径；复制成功后的任意时刻杀进程或元数据写入遇到配额失败，重启仍能在原账号恢复，绝不串号。
- 上传或建批次遇到 401 会先暂停当前账号队列、清除失效会话并返回账号登录页；用户重新账号登录，或主动用已绑定微信快捷登录后，只有重验仍是同一 `account.id` 才自动恢复原 UUID，若账号不同则旧原图继续留在旧账号命名空间。
- 仅在小程序回到前台、网络恢复或用户主动重试时续传，不宣称退出微信后仍能后台上传。
- multipart 的 `file` 是原始 JPEG/PNG，并发送 `photo_uuid`、拍摄时间、方向、宽高、原图 SHA-256、`original_size_bytes`、`original_filename`、`original_mime_type`、题名和日期；本机预览及其哈希不上传，云端预览由服务器统一生成。
- 服务器确认 `server_saved` 后立即安全删除本机原图，只保留不超过 100KB 的本机预览；失败或断网绝不删原图。进入前台会刷新批次，`desktop_imported` 后仍保留预览供本机查看。
- 自动识别接口只快速受理并返回 job；客户端不等待 OCR 长连接，仅在小程序前台轮询批次结果，进入后台立即停止请求，回到前台继续。
- 真实 API 与本地 H5 Mock 数据隔离；微信生产构建默认且强制使用真实 API。
- real/mock 运行时通过构建期 alias 物理隔离；微信正式产物不会包含 `mock.js`、样例照片或 Mock 请求函数，发布脚本会递归检查并拒绝混包。

## 技术基线

- uni-app Vue3 + TypeScript，DCloud `5.24.2026081301` 对应 npm 版本 `3.0.0-5020420260813001`。
- Vue `3.4.21`、Vite `5.2.8`、Vitest `3.2.6`。
- 接口前缀 `/api/mobile/v1`，当前客户端按服务器的“原图短期中转 + 独立云预览”契约实现；早期“只上传压缩图”的草案不再适用。

## 本机运行

```bash
npm install
npm run typecheck
npm test
npm run dev:h5
```

`dev:h5` 和 `build:h5` 显式使用 `.env.mock`，只用于本机界面验收。微信端默认连接 `https://api.shuiliyingxiang.cn`：

```bash
npm run dev:mp-weixin
npm run build:mp-weixin
```

## 微信开发者工具直连 GitHub

仓库源代码分支是 `codex/wechat-miniapp-v1`。仓库配置了自动发布流程：当源代码分支更新且仓库 Secret `WECHAT_APP_ID` 已配置后，GitHub Actions 会编译微信包并更新 `codex/wechat-mp-release` 分支。这个发布分支的根目录就是微信开发者工具可以直接打开的原生小程序目录。

在微信开发者工具中打开“版本管理”，配置本仓库的 GitHub 地址，选择 `codex/wechat-mp-release` 分支并执行“拉取”。后续源代码更新后，先在 GitHub Actions 等待发布分支完成，再在开发者工具中执行“拉取”。版本管理的 GitHub 拉取、提交和推送入口位于“版本管理”面板，具体认证名称随开发者工具版本可能略有不同。

发布流程默认使用当前小程序 AppID `wx8ad581f01bf4b09f`；如以后更换小程序，可在 GitHub Actions Secret 中设置 `WECHAT_APP_ID` 覆盖它。AppID 只写入编译产物的 `project.config.json`；AppSecret、服务器密钥和 OSS 凭据不进入 GitHub。

本机可双击 `scripts/同步并打开微信开发者工具.cmd`，脚本会拉取最新 `codex/wechat-mp-release`、检查本地目录没有未提交改动，然后自动打开微信开发者工具。微信开发者工具本身不会在远程分支变化后自动拉取，因此这个脚本是本机同步入口；如需完全无人值守，可将它加入 Windows 任务计划程序。

开发者工具已登录且服务端口开启后，也可直接上传开发版本：

```powershell
.\scripts\sync-wechat-devtools.ps1 -Upload -Version 1.2.20260828
```

第一次运行前，在微信开发者工具中打开「设置 → 安全设置 → 服务端口」并开启服务端口。这是微信工具允许外部脚本调用 CLI 的一次性授权；开启后，后续脚本可以自动拉取、刷新和打开项目。

`build:mp-weixin` 完成后会自动确认：

1. 构建包使用 real API 标记且没有 mock 标记；
2. 构建包物理不存在 `mock.js`、`mockRequest`、`mockUpload` 和 `samplePhotos`；
3. `dist/build/mp-weixin/custom-tab-bar/` 中原生 `index.js/index.json/index.wxml/index.wxss` 四文件完整。

正式生成体验版时，把 AppID 作为本机或 CI 环境变量传入，不写入仓库：

```powershell
$env:VITE_WECHAT_APP_ID = "你的小程序 AppID"
npm run build:mp-weixin:release
```

发布脚本会把 AppID 仅写入构建产物 `project.config.json`；缺少 AppID 或仍为游客 AppID 时，正式发布检查会直接失败。AppSecret 永远只配置在服务器环境中。

## 微信后台配置

1. 把 `https://api.shuiliyingxiang.cn` 配置为 request 与 uploadFile 合法域名，必须使用有效 HTTPS 证书。
2. 在《小程序用户隐私保护指引》中如实声明相机和相册用途。代码在调用 `chooseMedia` 前执行 `requirePrivacyAuthorize`；`manifest.json` 开启 `__usePrivacyCheck__`。
3. 当前 `requiredPrivateInfos` 没有错误填写 `chooseMedia`。照片选择属于隐私接口声明流程，不是可随意加入该数组的定位类配置项。
4. 服务器配置微信 AppID/AppSecret、真实 API 域名和存储凭据；任何密钥都不要写进本目录。
5. 微信开发者工具与后台最低基础库设置为 2.25.0 或更高；旧基础库仍可运行，但相册批量选择会降级到 9 张。

## 页面路径

- `pages/auth/bind`：账号密码登录、确认绑定当前微信，以及已绑定用户主动选择微信快捷登录。
- `pages/home/index`：现场工作台。
- `pages/project/select`：工程选择。
- `pages/destination/select`：单元/工序或其它影像目录选择。
- `pages/upload/index`：拍摄、相册、原图安全落盘、预览生成与入队。
- `pages/upload/confirm`：自动识别结果人工确认。
- `pages/queue/index`：断网队列、失败重试、电脑归档状态。
- `pages/library/index`：工程/其它、施工/监理图库。
- `pages/photo/detail`：照片与归档元数据只读详情。
- `pages/profile/index`：账号、服务器、本机空间与隐私说明。

## 测试与验收

`npm test` 覆盖状态机、50MB 原图/100KB 预览/160MB 队列/并发 2、分块 SHA-256、有界 EXIF 读取、缩边算法、真实 API 字段、幂等键、账号登录与确认绑定分步、主动微信快捷登录、token 过期返回登录页、登录内嵌 bootstrap、复制后崩溃恢复、元数据配额失败、双槽回退、跨账号 WAL 隔离、8MiB 路由、4MiB 分片断点/重复片/401/会话过期重传、异步 OCR 前台轮询、预览失败保原图及电脑归档后只释放原图。

真机验收仍需在微信开发者工具和 Android/iPhone 上执行：权限拒绝、20 张批量选择、飞行模式保存 80 张、彻底退出后恢复、弱网重试、登录过期、自动匹配低置信度、其它影像目录、电脑离线后恢复及 OSS 故障。80 张离线样本的“原图 + 全部预览”总占用必须不超过 160MB；真实可离线张数取决于每张原图大小。退出微信期间不会执行上传。
