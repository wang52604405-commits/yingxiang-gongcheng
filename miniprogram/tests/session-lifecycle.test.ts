import { describe, expect, it, vi } from 'vitest'
import { createSessionLifecycle } from '@/services/session-lifecycle'

describe('小程序生命周期登录闸门', () => {
  it('onLaunch/onShow 并发只验证一次，缓存账号在验证完成前绝不恢复上传', async () => {
    let resolveLogin!: (value: boolean) => void
    const ensure = vi.fn(() => new Promise<boolean>((resolve) => { resolveLogin = resolve }))
    const session: any = { ready: true, account: { id: 'old-cache', username: 'old' }, stage: 'authenticated' }
    const queue = {
      clearOwner: vi.fn(),
      setOwner: vi.fn(),
      startForegroundPolling: vi.fn(),
      stopForegroundPolling: vi.fn(),
      resume: vi.fn(async () => undefined),
    }
    const selection = { setOwner: vi.fn() }
    const lifecycle = createSessionLifecycle({ ensure, session, queue: queue as any, selection })

    const launch = lifecycle.activate()
    const show = lifecycle.activate()
    expect(launch).toBe(show)
    expect(ensure).toHaveBeenCalledTimes(1)
    expect(session.ready).toBe(false)
    expect(queue.clearOwner).toHaveBeenCalledTimes(1)
    expect(queue.setOwner).not.toHaveBeenCalled()
    expect(queue.resume).not.toHaveBeenCalled()

    session.account = { id: 'verified-account', username: 'verified' }
    resolveLogin(true)
    await Promise.all([launch, show])
    expect(queue.setOwner).toHaveBeenCalledWith('verified-account')
    expect(queue.resume).toHaveBeenCalledTimes(1)
    expect(selection.setOwner).toHaveBeenCalledWith('verified-account')
  })
})
