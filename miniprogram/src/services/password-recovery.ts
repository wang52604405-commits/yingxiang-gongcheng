import { API_BASE_URL } from '@/config/env'

type RecoveryResponse = {
  ok: boolean
  error?: string
  email?: string
  expires_in?: number
  message?: string
}

function requestRecovery(path: '/api/forgot-password' | '/api/reset-password', data: Record<string, string>): Promise<RecoveryResponse> {
  return new Promise((resolve, reject) => {
    uni.request({
      url: API_BASE_URL + path,
      method: 'POST',
      data,
      header: { 'Content-Type': 'application/json' },
      timeout: 20_000,
      success(response) {
        const body = response.data as RecoveryResponse | undefined
        if (response.statusCode >= 200 && response.statusCode < 300 && body?.ok) {
          resolve(body)
        } else {
          reject(new Error(String(body?.error || '找回密码失败，请稍后再试')))
        }
      },
      fail(error) {
        reject(new Error(error?.errMsg || '无法连接服务器，请检查网络后重试'))
      },
    })
  })
}

export async function sendPasswordRecoveryCode(account: string): Promise<RecoveryResponse> {
  const normalized = account.trim()
  if (!normalized) throw new Error('请输入注册账号')
  return requestRecovery('/api/forgot-password', { account: normalized })
}

export async function completePasswordRecovery(account: string, code: string, newPassword: string): Promise<void> {
  const normalized = account.trim()
  if (!normalized) throw new Error('请输入注册账号')
  if (!/^\d{6}$/.test(code.trim())) throw new Error('请输入6位邮箱验证码')
  if (newPassword.length < 8 || !/[A-Za-z]/.test(newPassword) || !/\d/.test(newPassword)) {
    throw new Error('新密码至少8位，并同时包含字母和数字')
  }
  await requestRecovery('/api/reset-password', {
    account: normalized,
    code: code.trim(),
    new_password: newPassword,
  })
}
