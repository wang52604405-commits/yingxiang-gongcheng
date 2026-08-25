type AuthExpiredHandler = (ownerAccountId: string) => Promise<void>

let handler: AuthExpiredHandler | null = null
let reconnecting: Promise<void> | null = null
let lastStartedAt = 0

export function registerAuthExpiredHandler(next: AuthExpiredHandler): void {
  handler = next
}

export function notifyAuthExpired(ownerAccountId: string): Promise<void> {
  if (reconnecting) return reconnecting
  if (!handler || Date.now() - lastStartedAt < 5_000) return Promise.resolve()
  lastStartedAt = Date.now()
  reconnecting = handler(ownerAccountId).finally(() => { reconnecting = null })
  return reconnecting
}

export function resetAuthExpiryCoordinatorForTest(): void {
  handler = null
  reconnecting = null
  lastStartedAt = 0
}
