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
    token: '',
    tokenGet: vi.fn(),
    tokenSet: vi.fn(),
    tokenClear: vi.fn(),
    accountLogin: vi.fn(),
    wechatLogin: vi.fn(),
    wechatBindConfirm: vi.fn(),
    loadBootstrap: vi.fn(),
    hydrateBootstrap: vi.fn(),
    clearBootstrapView: vi.fn(),
    applyBootstrap: vi.fn(),
    queueClearOwner: vi.fn(),
    queueSetOwner: vi.fn(),
    queueRecoverAuthFailures: vi.fn(),
    queueResume: vi.fn(async () => undefined),
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
  accountLogin: mocks.accountLogin,
  wechatLogin: mocks.wechatLogin,
  wechatBindConfirm: mocks.wechatBindConfirm,
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
  recoverAuthFailures: mocks.queueRecoverAuthFailures,
  resume: mocks.queueResume,
} }))
vi.mock('@/stores/selection', () => ({ selectionStorage: {
  clearOwner: mocks.selectionClearOwner,
} }))

describe('账号登录、微信绑定与 token 过期', () => {
  let storage: Map<string, any>
  let pages: any[]
  let login: ReturnType<typeof vi.fn>
  let reLaunch: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    vi.resetModules()
    Object.values(mocks).forEach((value) => {
      if (typeof value === 'function' && 'mockReset' in value) (value as any).mockReset()
    })
    mocks.token = ''
    mocks.tokenGet.mockImplementation(() => mocks.token)
    mocks.tokenSet.mockImplementation((value: string) => { mocks.token = value })
    mocks.tokenClear.mockImplementation(() => { mocks.token = '' })
    mocks.queueResume.mockResolvedValue(undefined)
    storage = new Map<string, any>()
    pages = [{ route: 'pages/home/index' }]
    ;(pages as any).at = undefined
    login = vi.fn(({ success }: any) => success({ code: 'new-code' }))
    reLaunch = vi.fn()
    ;(globalThis as any).uni = {
      getStorageSync: (key: string) => storage.get(key),
      setStorageSync: (key: string, value: unknown) => storage.set(key, value),
      removeStorageSync: (key: string) => storage.delete(key),
      login,
      reLaunch,
    }
    ;(globalThis as any).getCurrentPages = () => pages
  })

  it('无本地会话时直接进入账号页，不自动调用微信登录', async () => {
    const { ensureSession, sessionState } = await import('@/services/auth')
    await expect(ensureSession()).resolves.toBe(false)
    await vi.runAllTimersAsync()

    expect(login).not.toHaveBeenCalled()
    expect(mocks.wechatLogin).not.toHaveBeenCalled()
    expect(sessionState.stage).toBe('account_login')
    expect(reLaunch).toHaveBeenCalledWith({ url: '/pages/auth/bind' })
  })

  it('token 过期后回账号页并常驻显示原因，不再静默微信重登', async () => {
    mocks.token = 'expired-token'
    storage.set('engineering-image:account:v1', { id: 'A', username: 'old' })
    mocks.loadBootstrap.mockRejectedValue(new mocks.MockApiError('登录已过期', 'token_expired', false, 401))

    const { ensureSession, sessionState } = await import('@/services/auth')
    await expect(ensureSession()).resolves.toBe(false)
    await vi.runAllTimersAsync()

    expect(mocks.tokenClear).toHaveBeenCalled()
    expect(mocks.queueClearOwner).toHaveBeenCalled()
    expect(login).not.toHaveBeenCalled()
    expect(mocks.wechatLogin).not.toHaveBeenCalled()
    expect(sessionState.error).toBe('登录已过期，请重新登录')
    expect(sessionState.stage).toBe('account_login')
  })

  it('第一步只验证账号并生成绑定意图，不提前保存 token 或账号', async () => {
    pages = [{ route: 'pages/auth/bind' }]
    ;(pages as any).at = undefined
    mocks.accountLogin.mockResolvedValue({
      ok: true,
      account: { id: 'B', username: 'builder' },
      binding_intent: 'intent-B',
    })

    const { loginWithAccount, sessionState } = await import('@/services/auth')
    await loginWithAccount('builder', 'password1')

    expect(login).toHaveBeenCalledTimes(1)
    expect(mocks.accountLogin).toHaveBeenCalledWith('builder', 'password1', 'new-code', expect.any(String))
    expect(mocks.tokenSet).not.toHaveBeenCalled()
    expect(storage.has('engineering-image:account:v1')).toBe(false)
    expect(sessionState.account).toBeNull()
    expect(sessionState.pendingAccount?.id).toBe('B')
    expect(sessionState.bindingIntent).toBe('intent-B')
    expect(sessionState.stage).toBe('bind_wechat')
  })

  it('账号已验证后切后台再回来，仍保留微信绑定确认步骤', async () => {
    pages = [{ route: 'pages/auth/bind' }]
    mocks.accountLogin.mockResolvedValue({
      ok: true,
      account: { id: 'B', username: 'builder' },
      binding_intent: 'intent-B',
    })

    const { ensureSession, loginWithAccount, sessionState } = await import('@/services/auth')
    await loginWithAccount('builder', 'password1')
    sessionState.error = '请确认当前微信'

    await expect(ensureSession()).resolves.toBe(false)

    expect(sessionState.stage).toBe('bind_wechat')
    expect(sessionState.pendingAccount?.id).toBe('B')
    expect(sessionState.bindingIntent).toBe('intent-B')
    expect(sessionState.error).toBe('请确认当前微信')
    expect(mocks.tokenClear).not.toHaveBeenCalled()
    expect(mocks.accountLogin).toHaveBeenCalledTimes(1)
  })

  it('账号或网络验证失败时保留在登录页并常驻显示错误', async () => {
    pages = [{ route: 'pages/auth/bind' }]
    mocks.accountLogin.mockRejectedValue(new Error('账号或密码错误'))

    const { loginWithAccount, sessionState } = await import('@/services/auth')
    await expect(loginWithAccount('builder', 'wrong')).rejects.toThrow('账号或密码错误')

    expect(sessionState.stage).toBe('account_login')
    expect(sessionState.error).toBe('账号或密码错误')
    expect(mocks.tokenSet).not.toHaveBeenCalled()
    expect(reLaunch).not.toHaveBeenCalledWith({ url: '/pages/home/index' })
  })

  it('第二步确认绑定成功后才保存会话与 bootstrap 并进入工作台', async () => {
    pages = [{ route: 'pages/auth/bind' }]
    mocks.accountLogin.mockResolvedValue({ ok: true, account: { id: 'B', username: 'builder' }, binding_intent: 'intent-B' })
    const bootstrap = { ok: true, account: { id: 'B', username: 'builder' }, projects: [], current_project: null, queue: {}, recent_uploads: [], server_time: '' }
    mocks.wechatBindConfirm.mockResolvedValue({ ok: true, token: 'mobile-token', account: bootstrap.account, bootstrap })

    const { confirmWechatBinding, loginWithAccount, sessionState } = await import('@/services/auth')
    await loginWithAccount('builder', 'password1')
    await confirmWechatBinding()
    await vi.runAllTimersAsync()

    expect(mocks.wechatBindConfirm).toHaveBeenCalledWith('intent-B')
    expect(mocks.tokenSet).toHaveBeenCalledWith('mobile-token')
    expect(storage.get('engineering-image:account:v1')).toEqual(bootstrap.account)
    expect(mocks.applyBootstrap).toHaveBeenCalledWith('B', bootstrap)
    expect(mocks.queueSetOwner).toHaveBeenCalledWith('B')
    expect(mocks.queueRecoverAuthFailures).toHaveBeenCalled()
    expect(sessionState.stage).toBe('authenticated')
    expect(reLaunch).toHaveBeenCalledWith({ url: '/pages/home/index' })
  })

  it('微信快捷登录只在用户主动点击后执行，未绑定时保留账号页错误', async () => {
    pages = [{ route: 'pages/auth/bind' }]
    mocks.wechatLogin.mockResolvedValue({ ok: true, binding_required: true })

    const { quickWechatLogin, sessionState } = await import('@/services/auth')
    await expect(quickWechatLogin()).rejects.toThrow('当前微信尚未绑定账号')

    expect(login).toHaveBeenCalledTimes(1)
    expect(mocks.wechatLogin).toHaveBeenCalledTimes(1)
    expect(mocks.tokenSet).not.toHaveBeenCalled()
    expect(sessionState.stage).toBe('account_login')
    expect(sessionState.error).toContain('当前微信尚未绑定账号')
  })

  it('切换账号只清理本地会话并返回账号页，不会立即登录回原微信', async () => {
    mocks.token = 'valid-token'
    storage.set('engineering-image:account:v1', { id: 'A', username: 'old' })
    const { signOut, sessionState } = await import('@/services/auth')
    signOut()
    await vi.runAllTimersAsync()

    expect(mocks.tokenClear).toHaveBeenCalled()
    expect(login).not.toHaveBeenCalled()
    expect(mocks.wechatLogin).not.toHaveBeenCalled()
    expect(sessionState.account).toBeNull()
    expect(sessionState.stage).toBe('account_login')
    expect(reLaunch).toHaveBeenCalledWith({ url: '/pages/auth/bind' })
  })
})
