const PENDING_INVITE_KEY = 'engineering-image:pending-project-invite:v1'
const HANDLED_INVITES_KEY = 'engineering-image:handled-launch-invites:v1'
const ACCOUNT_KEY = 'engineering-image:account:v1'
const PENDING_INVITE_TTL_MS = 15 * 60 * 1000
// WeChat's actual launch/show event scene, not a cached getEnterOptionsSync result.
// https://github.com/wechat-miniprogram/api-typings/blob/master/types/wx/lib.wx.app.d.ts
const INVITE_ENTRY_SCENES = new Set([1007, 1008, 1011, 1012, 1013, 1036, 1044, 1047, 1048, 1049, 1073, 1074, 1096])
interface PendingInvite { code: string; expires_at: number }
interface HandledInvite { code: string; owner: string; reason: 'completed' | 'invalid' | 'expired'; handled_at: number }
let lastEntryFingerprint = ''
let discardedInviteEntry = false
let launchInviteToNavigate = ''

function owner(): string { return String(uni.getStorageSync(ACCOUNT_KEY)?.id || 'unbound') }
function handledInvites(): HandledInvite[] {
  const rows = uni.getStorageSync(HANDLED_INVITES_KEY)
  return Array.isArray(rows) ? rows.filter((row) => row && typeof row.code === 'string' && typeof row.owner === 'string') : []
}
export function normalizeInviteCode(value: unknown): string {
  return String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 10)
}
function markHandled(code: string, reason: HandledInvite['reason'], now: number): void {
  if (code.length !== 10) return
  const account = reason === 'invalid' ? '*' : owner()
  const rows = handledInvites().filter((row) => !(row.code === code && row.owner === account))
  uni.setStorageSync(HANDLED_INVITES_KEY, [{ code, owner: account, reason, handled_at: now }, ...rows].slice(0, 100))
}
export function isHandledLaunchInvite(value: unknown): boolean {
  const code = normalizeInviteCode(value)
  const account = owner()
  return handledInvites().some((row) => row.code === code && (row.owner === account || row.owner === '*'))
}
/** Explicit manual input may retry a code. Automatic launch replay cannot. */
export function rememberPendingInvite(value: unknown, now = Date.now()): string {
  const code = normalizeInviteCode(value)
  if (code.length !== 10) return ''
  discardedInviteEntry = false
  uni.setStorageSync(PENDING_INVITE_KEY, { code, expires_at: now + PENDING_INVITE_TTL_MS } satisfies PendingInvite)
  return code
}
export function peekPendingInvite(now = Date.now()): string {
  const pending = uni.getStorageSync(PENDING_INVITE_KEY) as PendingInvite | null
  if (!pending?.code || !pending.expires_at || pending.expires_at <= now) {
    if (pending?.code) markHandled(normalizeInviteCode(pending.code), 'expired', now)
    uni.removeStorageSync(PENDING_INVITE_KEY)
    return ''
  }
  return normalizeInviteCode(pending.code)
}
export function consumePendingInvite(now = Date.now()): string {
  const code = peekPendingInvite(now)
  if (code) { markHandled(code, 'completed', now); uni.removeStorageSync(PENDING_INVITE_KEY) }
  return code
}
export function clearPendingInvite(): void { uni.removeStorageSync(PENDING_INVITE_KEY) }
export function invalidatePendingInvite(value: unknown, now = Date.now()): void {
  const code = normalizeInviteCode(value)
  markHandled(code, 'invalid', now)
  if (peekPendingInvite(now) === code) clearPendingInvite()
}
export function isInvalidInviteError(error: unknown): boolean {
  const reason = error as { code?: string; message?: string }
  return /invite.*(expired|revoked|invalid|not_found|unavailable)|(expired|revoked|invalid).*invite/i.test(String(reason?.code || ''))
    || /邀请码.*(过期|失效|撤销|无效|不存在)|邀请.*(已过期|已撤销)/.test(String(reason?.message || ''))
}
export function isDiscardedInviteEntry(): boolean { return discardedInviteEntry }
export function clearDiscardedInviteEntry(): void { discardedInviteEntry = false }
export function takeLaunchInviteNavigation(): string {
  const code = launchInviteToNavigate
  launchInviteToNavigate = ''
  return code && peekPendingInvite() === code ? code : ''
}
/** A page query alone is not evidence of a new share; WeChat also restores old queries. */
export function inviteCodeForJoinPage(query: any): string {
  const pending = peekPendingInvite()
  const queried = normalizeInviteCode(query?.code || query?.invite || '')
  if (pending) { launchInviteToNavigate = ''; return pending }
  if (!queried) return ''
  discardedInviteEntry = true
  return ''
}
export function rememberLaunchInvite(options: any, phase: 'launch' | 'show' = 'launch', now = Date.now()): string {
  const query = options?.query && typeof options.query === 'object' ? options.query : {}
  let encodedScene = ''
  try { encodedScene = decodeURIComponent(String(query.scene || '')) } catch { /* Malformed shared data is not an invite. */ }
  const sceneMatch = encodedScene.match(/(?:^|[?&])(?:invite|code)=([^&]+)/i)
  const code = normalizeInviteCode(query.invite || query.code || sceneMatch?.[1] || encodedScene)
  const path = String(options?.path || '').replace(/^\//, '')
  const scene = Number(options?.scene || 0)
  const pending = peekPendingInvite(now)
  if (!INVITE_ENTRY_SCENES.has(scene) || code.length !== 10) {
    // A cold normal reopen is not a request to resume yesterday's invitation.
    if (phase === 'launch') { clearPendingInvite(); launchInviteToNavigate = '' }
    discardedInviteEntry = (Boolean(code) || path === 'pages/project/join') && !(phase === 'show' && pending)
    return ''
  }
  const fingerprint = JSON.stringify([owner(), scene, path, code])
  if (isHandledLaunchInvite(code)) {
    if (pending === code) clearPendingInvite()
    discardedInviteEntry = true
    lastEntryFingerprint = fingerprint
    return ''
  }
  if (phase === 'show' && fingerprint === lastEntryFingerprint) {
    // onLaunch + onShow, camera/permission return, or stale repeated entry options.
    discardedInviteEntry = pending !== code
    return pending === code ? code : ''
  }
  lastEntryFingerprint = fingerprint
  const saved = rememberPendingInvite(code, now)
  launchInviteToNavigate = saved
  return saved
}
