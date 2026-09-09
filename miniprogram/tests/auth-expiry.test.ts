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
    wechatJoin: vi.fn(),
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
  wechatJoin: mocks.wechatJoin,
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

  it('从微信邀请进入时，账号绑定完成后恢复加入项目页面', async () => {
    pages = [{ route: 'pages/auth/bind' }]
    mocks.accountLogin.mockResolvedValue({ ok: true, account: { id: 'B', username: 'builder' }, binding_intent: 'intent-B' })
    const bootstrap = { ok: true, account: { id: 'B', username: 'builder' }, projects: [], current_project: null, queue: {}, recent_uploads: [], server_time: '' }
    mocks.wechatBindConfirm.mockResolvedValue({ ok: true, token: 'mobile-token', account: bootstrap.account, bootstrap })

    const { rememberPendingInvite } = await import('@/services/pending-invite')
    rememberPendingInvite('TEAM123456')
    const { confirmWechatBinding, loginWithAccount } = await import('@/services/auth')
    await loginWithAccount('builder', 'password1')
    await confirmWechatBinding()
    await vi.runAllTimersAsync()

    expect(reLaunch).toHaveBeenCalledWith({ url: '/pages/project/join?code=TEAM123456' })
    expect(reLaunch).not.toHaveBeenCalledWith({ url: '/pages/home/index' })
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
  it('受邀新成员提交真实姓名手机号后等待审核，不获得项目权限', async () => {
    pages = [{ route: 'pages/auth/bind' }]
    const project = { id: 'owner:project', name: '邀请项目' }
    mocks.wechatJoin.mockResolvedValue({ ok: true, token: 'member-token', account: { id: 'member', username: 'wx_member', display_name: '张三' }, join_request: { id: 'req-1', status: 'pending', applicant_account_id: 'member', project_id: project.id }, pending_approval: true, bootstrap: { ok: true, projects: [] } })
    const { joinProjectWithWechat, sessionState } = await import('@/services/auth')
    const { peekPendingInvite } = await import('@/services/pending-invite')
    await joinProjectWithWechat('TEAM123456', ' 张三 ', '13812345678')
    await vi.runAllTimersAsync()
    expect(login).toHaveBeenCalledTimes(1)
    expect(mocks.wechatJoin).toHaveBeenCalledWith('TEAM123456', '张三', '13812345678', 'new-code', expect.any(String))
    expect(mocks.accountLogin).not.toHaveBeenCalled()
    expect(mocks.applyBootstrap).toHaveBeenCalledWith('member', { ok: true, projects: [] })
    expect(peekPendingInvite()).toBe('')
    expect(sessionState.stage).toBe('authenticated')
    expect(reLaunch).toHaveBeenCalledWith({ url: '/pages/project/request-status?id=req-1' })
  })

  it('邀请过期错误保留输入和邀请码，重试重新获取微信 code', async () => {
    mocks.wechatJoin.mockRejectedValue(new Error('邀请码已过期，请联系邀请人'))
    const { joinProjectWithWechat, sessionState } = await import('@/services/auth')
    const { peekPendingInvite } = await import('@/services/pending-invite')
    await expect(joinProjectWithWechat('TEAM123456', '张三', '13812345678')).rejects.toThrow('邀请码已过期')
    expect(sessionState.error).toContain('邀请码已过期')
    expect(peekPendingInvite()).toBe('TEAM123456')
    expect(mocks.tokenSet).not.toHaveBeenCalled()
    await expect(joinProjectWithWechat('TEAM123456', '张三', '13812345678')).rejects.toThrow()
    expect(login).toHaveBeenCalledTimes(2)
  })

  it.each(['cancel', 'new-invite'])('微信加入请求结束前发生 %s，不接受旧账号响应', async (change) => {
    let finish!: (value: any) => void
    mocks.wechatJoin.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    const { joinProjectWithWechat, cancelWechatJoin } = await import('@/services/auth')
    const { rememberPendingInvite } = await import('@/services/pending-invite')
    const joining = joinProjectWithWechat('TEAM123456', '张三', '13812345678')
    await Promise.resolve()
    if (change === 'cancel') cancelWechatJoin()
    else rememberPendingInvite('TEAM654321')
    finish({ ok: true, token: 'stale-token', account: { id: 'old' } })
    await expect(joining).rejects.toThrow('加入操作已取消')
    expect(mocks.tokenSet).not.toHaveBeenCalled()
  })

  it('手机号缺失时不获取微信凭证，也不发送入项申请', async () => {
    const { joinProjectWithWechat } = await import('@/services/auth')
    await expect(joinProjectWithWechat('TEAM123456', '张三', '')).rejects.toThrow('手机号')
    expect(login).not.toHaveBeenCalled()
    expect(mocks.wechatJoin).not.toHaveBeenCalled()
  })

  it('没有审批申请或已存在成员证明的旧直入响应不能授予会话', async () => {
    mocks.wechatJoin.mockResolvedValue({ ok: true, token: 'unsafe-token', account: { id: 'member' }, project: { id: 'p' }, bootstrap: { ok: true, projects: [{ id: 'p' }] } })
    const { joinProjectWithWechat } = await import('@/services/auth')
    await expect(joinProjectWithWechat('TEAM123456', '张三', '13812345678')).rejects.toThrow('申请响应不完整')
    expect(mocks.tokenSet).not.toHaveBeenCalled()
  })

})
