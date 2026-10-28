import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  delete (globalThis as { uni?: unknown }).uni
  vi.resetModules()
})

describe('小程序找回密码', () => {
  it('向已绑定邮箱的账号发送验证码', async () => {
    const request = vi.fn(({ success }) => success({ statusCode: 200, data: { ok: true, email: 'a***@example.com' } }))
    ;(globalThis as { uni?: unknown }).uni = { request }
    const { sendPasswordRecoveryCode } = await import('@/services/password-recovery')
    await expect(sendPasswordRecoveryCode(' customer ')).resolves.toMatchObject({ email: 'a***@example.com' })
    expect(request).toHaveBeenCalledWith(expect.objectContaining({
      method: 'POST',
      data: { account: 'customer' },
    }))
  })

  it('未绑定邮箱时明确提示联系管理员，不隐瞒服务器错误', async () => {
    const request = vi.fn(({ success }) => success({
      statusCode: 400, data: { ok: false, error: '该账号未绑定邮箱，无法通过邮箱找回。请联系管理员重置密码' },
    }))
    ;(globalThis as { uni?: unknown }).uni = { request }
    const { sendPasswordRecoveryCode } = await import('@/services/password-recovery')
    await expect(sendPasswordRecoveryCode('customer')).rejects.toThrow('请联系管理员重置密码')
  })

  it('仅提交格式合规的验证码和新密码', async () => {
    const request = vi.fn(({ success }) => success({ statusCode: 200, data: { ok: true } }))
    ;(globalThis as { uni?: unknown }).uni = { request }
    const { completePasswordRecovery } = await import('@/services/password-recovery')
    await expect(completePasswordRecovery('customer', '123', 'NewPassword2026')).rejects.toThrow('6位')
    await expect(completePasswordRecovery('customer', '123456', 'abcdefghi')).rejects.toThrow('字母和数字')
    await completePasswordRecovery(' customer ', ' 123456 ', 'NewPassword2026')
    expect(request).toHaveBeenCalledTimes(1)
    expect(request).toHaveBeenCalledWith(expect.objectContaining({
      data: { account: 'customer', code: '123456', new_password: 'NewPassword2026' },
    }))
  })
})
