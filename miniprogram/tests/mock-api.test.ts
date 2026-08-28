import { describe, expect, it } from 'vitest'
import { mockRequest } from '@/api/mock'

describe('体验环境 API', () => {
  it('账号登录与确认绑定遵循两阶段契约', async () => {
    const accountLogin = await mockRequest<any>('POST', '/auth/account-login', {
      username: '体验账号', password: 'password1', code: 'mock-code', app_id: 'mock-app',
    })
    const confirmed = await mockRequest<any>('POST', '/auth/wechat-bind-confirm', {
      binding_intent: accountLogin.binding_intent,
    })
    const quickLogin = await mockRequest<any>('POST', '/auth/wechat-login', { code: 'mock-code', app_id: 'mock-app' })

    expect(accountLogin).toMatchObject({ account: { id: 'mock-account' }, binding_intent: 'mock-binding-intent' })
    expect(accountLogin).not.toHaveProperty('token')
    expect(confirmed).toMatchObject({ token: 'mock-token', bootstrap: { account: { id: 'mock-account' } } })
    expect(quickLogin).toMatchObject({ token: 'mock-token', bootstrap: { account: { id: 'mock-account' } } })
  })

  it('专业采集清单有可操作数据且支持类型筛选', async () => {
    const all = await mockRequest<any>('GET', '/projects/default/requirements')
    const required = await mockRequest<any>('GET', '/projects/default/requirements?required_type=required')

    expect(all.summary).toEqual({ total: 3, required: 1, conditional: 1, recommended: 1 })
    expect(all.requirements).toHaveLength(3)
    expect(required.requirements).toHaveLength(1)
    expect(required.requirements[0]).toMatchObject({ template_code: 'SL-JZ-001', required_type: 'required' })
  })

  it('影像库返回与列表一致的总数', async () => {
    const response = await mockRequest<any>('GET', '/photos?project_id=default&scope=engineering&category=construction')

    expect(response.total).toBe(response.photos.length)
    expect(response.total).toBe(2)
  })
})
