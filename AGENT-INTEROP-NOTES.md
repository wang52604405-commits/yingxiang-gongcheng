# DSH 多 Agent 互通 / 委派 — 现状与路线（v3）

> 你要的是**互通 / 委派**（谁都能指派谁去干活），不是把资产集成进 DSH。已卸载方向不对的 dsh-bridges。

## 一、本机外部 agent 现状（已验证）

| CLI | 非交互入口 | ACP | 实测结果 |
|---|---|---|---|
| **opencode** | `opencode run "…"` / `opencode serve` | ✅ `opencode acp` | ✅ **能真正跑任务**（用 DeepSeek 模型） |
| codex | `codex exec "…"` | — | ⚠️ 模型缓存报错 `unknown variant "max"`，需修 |
| claude | `claude -p "…"` | — | ⚠️ `Not logged in`，需 `claude /login` |

**关键结论：DSH 已经能真正委派任务给 OpenCode 并回收结果**（互通的通道打通）。
opencode 默认模型 `gpt-5.6-luna` 在部分区域被拒，改用 `opencode-go/deepseek-v4-flash` 即可。

实测：
```
$ opencode run -m opencode-go/deepseek-v4-flash "Reply with exactly: OK"
> build · deepseek-v4-flash
OK
```

## 二、已做好的轻量委派通道（可立即用）

脚本：`E:\use\agent-delegate.sh`（已实测 opencode 通路，返回真实结果）

```sh
agent-delegate.sh opencode "做一件事"      # ✅ 可用
agent-delegate.sh codex   "做一件事"      # 需先修 codex 模型缓存
agent-delegate.sh claude  "做一件事"      # 需先 claude /login
OPENCODE_MODEL=opencode-go/deepseek-v4-pro agent-delegate.sh opencode "…"   # 换模型
```

## 三、真正的「谁都能指派谁」网状桥接层（推荐插件）

### dsh-plugin-subagents
- 作用：接管官方 `subagent`/`subagent_fork`，支持原生子代理 + **桥接子代理**到 Claude Code / Codex / **任意 ACP agent（opencode 走 `opencode acp`）**；提供 `subagent_agents`、`subagent_roles`、`subagent_submit`、`subagent_wait` 等。
- 仓库：https://github.com/Luck9Star/dsh-plugin-subagents （已 clone 到 `~/.dsh/deps/dsh-plugin-subagents`）

### 安装步骤（README）
```sh
git clone https://github.com/Luck9Star/dsh-plugin-subagents
cd dsh-plugin-subagents
npm install
npm run setup:peer            # 避免出现两份 dsh-tools（不跑会崩）
dsh plugin --profile desktop add "$(pwd)"
./patches/install.sh          # Windows: patches\install.ps1（宿主补丁，必须）
./patches/verify.sh           # 可选体检
./scripts/install-preset.sh standard
# 重启/新会话
```

## 四、为什么这个「网状插件」暂未安装
1. 改 DSH 本体 + 给核心 `dsh-tools`/`dsh-subagent` 打补丁（Stage A 必修、Stage B 版本门槛 0.1.0-rc.6），影响所有会话，无法当前热验证，需重启。
2. `Resolve-LiveRoot` 走 npm 全局 `dsh`，与桌面 app 实际根（app.asar.unpacked）可能不同，需用 `DSH_HARNESS_ROOT` 指到正确根。
3. GUI 是隔离 free-mode 会话，要让其看到需同时写产品 node_modules + `.dsh-desktop-links.json`。
4. codex/claude 本身未就绪，装了也到不了「能出结果」。

## 五、下一步
- **可立即**：用 `E:\use\agent-delegate.sh` 把任务派给 opencode（已验证）。
- **要全通**：① `claude /login`；② 修 codex 模型缓存；③ 确认接受改 DSH 本体后，装 dsh-plugin-subagents。

## 六、回滚
- profile 备份：`~/.dsh/backups/desktop-20260823-120806`
- 打补丁前会再备份 `app.asar.unpacked\node_modules\@deepseek-ai\dsh-tools` 与 `dsh-subagent`。
