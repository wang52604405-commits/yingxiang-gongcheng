export interface SessionLifecycleDependencies {
  ensure: () => Promise<boolean>
  session: { ready: boolean; account: { id: string | number } | null }
  queue: {
    clearOwner(): void
    setOwner(accountId: string | number): void
    startForegroundPolling(): void
    stopForegroundPolling(): void
    resume(reason: 'app-show'): Promise<void>
  }
  selection: { setOwner(accountId: string | number): void }
}

export function createSessionLifecycle(dependencies: SessionLifecycleDependencies) {
  let activation: Promise<boolean> | null = null

  function activate(): Promise<boolean> {
    if (activation) return activation
    dependencies.session.ready = false
    dependencies.queue.clearOwner()
    activation = (async () => {
      const authenticated = await dependencies.ensure()
      const account = dependencies.session.account
      if (!authenticated || !account) return false
      dependencies.selection.setOwner(account.id)
      dependencies.queue.setOwner(account.id)
      dependencies.queue.startForegroundPolling()
      await dependencies.queue.resume('app-show')
      return true
    })().finally(() => { activation = null })
    return activation
  }

  function hide(): void {
    dependencies.queue.stopForegroundPolling()
  }

  return { activate, hide }
}
