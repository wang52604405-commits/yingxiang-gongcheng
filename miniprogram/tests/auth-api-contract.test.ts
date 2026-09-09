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
  it('受邀成员入口只发送微信凭证、邀请码和姓名，并规范化目标项目', async () => {
    mocks.apiRequest.mockResolvedValue({ ok: true, token: 'member-token', project: { project_id: 'owner:p', project_name: '工程' } })
    const response = await mobileApi.wechatJoin('TEAM123456', '张三', '13812345678', 'fresh-code', 'wx-app-id')
    expect(mocks.apiRequest).toHaveBeenCalledWith('POST', '/auth/wechat-join', { code: 'fresh-code', app_id: 'wx-app-id', invite_code: 'TEAM123456', display_name: '张三', phone: '13812345678' }, false)
    expect(response.project?.id).toBe('owner:p')
    expect(response.project?.name).toBe('工程')
  })

  it('已登录账号同样提交姓名手机号，并保留待审批状态而不制造项目', async () => {
    mocks.apiRequest.mockResolvedValue({ ok: true, pending_approval: true, join_request: { id: 7, status: 'pending', applicant_account_id: 9, project_id: 'owner:p' } })
    const response = await mobileApi.joinProjectInvite('TEAM123456', '张三', '13812345678')
    expect(mocks.apiRequest).toHaveBeenCalledWith('POST', '/project-invites/join', { code: 'TEAM123456', display_name: '张三', phone: '13812345678' })
    expect(response.project).toBeUndefined()
    expect(response.join_request?.id).toBe('7')
    expect(response.pending_approval).toBe(true)
  })

})
