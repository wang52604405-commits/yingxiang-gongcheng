import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  class MockApiError extends Error {
    code: string
    retryable: boolean
    statusCode?: number
    constructor(message: string, code: string, retryable: boolean, statusCode?: number) {
      super(message)
      this.code = code
      this.retryable = retryable
      this.statusCode = statusCode
    }
  }
  return {
    MockApiError,
    token: 'expired-token',
    tokenGet: vi.fn(),
    tokenSet: vi.fn(),
    tokenClear: vi.fn(),
    wechatLogin: vi.fn(),
    loadBootstrap: vi.fn(),
    hydrateBootstrap: vi.fn(),
    clearBootstrapView: vi.fn(),
    applyBootstrap: vi.fn(),
    queueClearOwner: vi.fn(),
    queueSetOwner: vi.fn(),
    selectionClearOwner: vi.fn(),
  }
})

vi.mock('@/api/client', () => ({
  ApiError: mocks.MockApiError,
  tokenStorage: {
    get: mocks.tokenGet,
    set: mocks.tokenSet,
    clear: mocks.tokenClear,
  },
}))
vi.mock('@/api/mobile', () => ({ mobileApi: {
  wechatLogin: mocks.wechatLogin,
  wechatBind: vi.fn(),
} }))
vi.mock('@/stores/bootstrap', () => ({
  hydrateBootstrap: mocks.hydrateBootstrap,
  loadBootstrap: mocks.loadBootstrap,
  clearBootstrapView: mocks.clearBootstrapView,
  applyBootstrap: mocks.applyBootstrap,
}))
vi.mock('@/services/queue-runtime', () => ({ queueRuntime: {
  clearOwner: mocks.queueClearOwner,
  setOwner: mocks.queueSetOwner,
} }))
vi.mock('@/stores/selection', () => ({ selectionStorage: {
  clearOwner: mocks.selectionClearOwner,
} }))

describe('自动登录与 token 过期', () => {
  beforeEach(() => {
    vi.resetModules()
    Object.values(mocks).forEach((value) => { if (typeof value === 'function' && 'mockReset' in value) (value as any).mockReset() })
    mocks.token = 'expired-token'
    mocks.tokenGet.mockImplementation(() => mocks.token)
    mocks.tokenSet.mockImplementation((value: string) => { mocks.token = value })
    mocks.tokenClear.mockImplementation(() => { mocks.token = '' })
    const storage = new Map<string, any>([['engineering-image:account:v1', { id: 'A', username: 'old' }]])
    ;(globalThis as any).uni = {
      getStorageSync: (key: string) => storage.get(key),
      setStorageSync: (key: string, value: unknown) => storage.set(key, value),
      removeStorageSync: (key: string) => storage.delete(key),
      login: ({ success }: any) => success({ code: 'new-code' }),
      showToast: vi.fn(),
      reLaunch: vi.fn(),
    }
    ;(globalThis as any).getCurrentPages = () => []
  })

  it('启动先 bootstrap 验证；401 清旧 token、暂停旧队列，再重新微信登录和 bootstrap', async () => {
    mocks.loadBootstrap
      .mockRejectedValueOnce(new mocks.MockApiError('登录已过期', 'token_expired', false, 401))
      .mockResolvedValueOnce({ ok: true, account: { id: 'B', username: 'new' }, projects: [], current_project: null, queue: {}, recent_uploads: [], server_time: '' })
    mocks.wechatLogin.mockResolvedValue({ ok: true, token: 'new-token', account: { id: 'B', username: 'new' } })

    const { ensureSession, sessionState } = await import('@/services/auth')
    await expect(ensureSession()).resolves.toBe(true)
    expect(mocks.loadBootstrap).toHaveBeenCalledTimes(2)
    expect(mocks.wechatLogin).toHaveBeenCalledTimes(1)
    expect(mocks.tokenClear).toHaveBeenCalledTimes(1)
    expect(mocks.queueClearOwner).toHaveBeenCalledTimes(1)
    expect(mocks.queueSetOwner).toHaveBeenCalledWith('B')
    expect(sessionState.account?.id).toBe('B')
    expect(mocks.queueClearOwner.mock.invocationCallOrder[0]).toBeLessThan(mocks.queueSetOwner.mock.invocationCallOrder[0])
  })

  it('登录响应自带 bootstrap 时立即写入，随后刷新失败也不丢工程数据', async () => {
    mocks.token = ''
    const embedded = { ok: true, account: { id: 'B', username: 'new' }, projects: [{ id: 'YNLQ', code: 'YNLQ', name: '邯郸市永年区洺河龙泉缓洪工程' }], current_project: null, queue: { desktop_pending: 2 }, recent_uploads: [], server_time: '' }
    mocks.wechatLogin.mockResolvedValue({ ok: true, token: 'new-token', account: embedded.account, bootstrap: embedded })
    mocks.loadBootstrap.mockRejectedValue(new Error('暂时离线'))

    const { ensureSession } = await import('@/services/auth')
    await expect(ensureSession()).resolves.toBe(true)
    expect(mocks.applyBootstrap).toHaveBeenCalledWith('B', embedded)
    expect(mocks.loadBootstrap).toHaveBeenCalledTimes(1)
    expect(mocks.queueSetOwner).toHaveBeenCalledWith('B')
  })
})
