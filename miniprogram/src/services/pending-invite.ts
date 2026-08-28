const PENDING_INVITE_KEY = 'engineering-image:pending-project-invite:v1'
const PENDING_INVITE_TTL_MS = 15 * 60 * 1000

interface PendingInvite {
  code: string
  expires_at: number
}

export function normalizeInviteCode(value: unknown): string {
  return String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 10)
}

export function rememberPendingInvite(value: unknown, now = Date.now()): string {
  const code = normalizeInviteCode(value)
  if (code.length !== 10) return ''
  uni.setStorageSync(PENDING_INVITE_KEY, { code, expires_at: now + PENDING_INVITE_TTL_MS } satisfies PendingInvite)
  return code
}

export function peekPendingInvite(now = Date.now()): string {
  const pending = uni.getStorageSync(PENDING_INVITE_KEY) as PendingInvite | null
  if (!pending?.code || !pending.expires_at || pending.expires_at <= now) {
    uni.removeStorageSync(PENDING_INVITE_KEY)
    return ''
  }
  return normalizeInviteCode(pending.code)
}

export function consumePendingInvite(now = Date.now()): string {
  const code = peekPendingInvite(now)
  if (code) uni.removeStorageSync(PENDING_INVITE_KEY)
  return code
}

export function clearPendingInvite(): void {
  uni.removeStorageSync(PENDING_INVITE_KEY)
}

export function rememberLaunchInvite(options: any): string {
  const query = options?.query && typeof options.query === 'object' ? options.query : {}
  const direct = query.invite || query.code
  if (direct) return rememberPendingInvite(direct)
  const scene = decodeURIComponent(String(query.scene || ''))
  const sceneMatch = scene.match(/(?:^|[?&])(?:invite|code)=([^&]+)/i)
  return rememberPendingInvite(sceneMatch?.[1] || scene)
}
