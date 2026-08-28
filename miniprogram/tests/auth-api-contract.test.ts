import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  apiBinaryRequest: vi.fn(),
  apiUploadPhoto: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  apiRequest: mocks.apiRequest,
  apiBinaryRequest: mocks.apiBinaryRequest,
  apiUploadPhoto: mocks.apiUploadPhoto,
}))

import { mobileApi } from '@/api/mobile'

describe('两阶段登录 API 契约', () => {
  beforeEach(() => {
    mocks.apiRequest.mockReset()
  })

  it('账号验证同时提交微信 code，但不请求 token', async () => {
    mocks.apiRequest.mockResolvedValue({ ok: true, account: { id: 32, username: 'tester' }, binding_intent: 'intent-32' })

    await mobileApi.accountLogin('tester', 'password1', 'wx-code', 'wx-app-id')

    expect(mocks.apiRequest).toHaveBeenCalledWith('POST', '/auth/account-login', {
      username: 'tester',
      password: 'password1',
      code: 'wx-code',
      app_id: 'wx-app-id',
    }, false)
  })

  it('用户确认后只提交 binding_intent 完成微信绑定', async () => {
    mocks.apiRequest.mockResolvedValue({ ok: true, token: 'mobile-token', account: { id: 32, username: 'tester' } })

    await mobileApi.wechatBindConfirm('intent-32')

    expect(mocks.apiRequest).toHaveBeenCalledWith('POST', '/auth/wechat-bind-confirm', {
      binding_intent: 'intent-32',
    }, false)
  })
})
