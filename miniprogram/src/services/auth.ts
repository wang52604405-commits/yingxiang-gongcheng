import { reactive } from 'vue'
import { API_MODE, WECHAT_APP_ID } from '@/config/env'
import { mobileApi } from '@/api/mobile'
import { ApiError, tokenStorage } from '@/api/client'
import type { Account } from '@/types/domain'
import { applyBootstrap, clearBootstrapView, hydrateBootstrap, loadBootstrap } from '@/stores/bootstrap'
import { queueRuntime } from '@/services/queue-runtime'
import { selectionStorage } from '@/stores/selection'
import { registerAuthExpiredHandler } from './auth-expiry-coordinator'

const ACCOUNT_KEY = 'engineering-image:account:v1'
const BINDING_TICKET_KEY = 'engineering-image:binding-ticket:v1'

export const sessionState = reactive<{
  ready: boolean
  account: Account | null
  bindingRequired: boolean
}>({
  ready: false,
  account: (uni.getStorageSync(ACCOUNT_KEY) || null) as Account | null,
  bindingRequired: false,
})

function getLoginCode(): Promise<string> {
  if (API_MODE === 'mock') return Promise.resolve('mock-code')
  return new Promise((resolve, reject) => {
    uni.login({ provider: 'weixin', success: (result) => resolve(result.code), fail: reject })
  })
}

function moveToBinding(): void {
  const currentRoute = getCurrentPages().at(-1)?.route || ''
  if (currentRoute === 'pages/auth/bind') return
  setTimeout(() => uni.reLaunch({ url: '/pages/auth/bind' }), 0)
}

export async function ensureSession(): Promise<boolean> {
  if (tokenStorage.get()) {
    if (sessionState.account) {
      hydrateBootstrap(sessionState.account.id)
      try {
        const bootstrap = await loadBootstrap(sessionState.account.id)
        sessionState.account = bootstrap.account
        uni.setStorageSync(ACCOUNT_KEY, bootstrap.account)
      } catch (error) {
        const unauthorized = error instanceof ApiError && (error.statusCode === 401 || ['unauthorized', 'token_expired'].includes(error.code))
        if (unauthorized) {
          tokenStorage.clear()
          uni.removeStorageSync(ACCOUNT_KEY)
          sessionState.account = null
          queueRuntime.clearOwner()
          selectionStorage.clearOwner()
          clearBootstrapView()
        } else {
          // 离线启动继续使用当前账号独立缓存，联网后页面会再次拉取。
          sessionState.ready = true
          return true
        }
      }
      if (tokenStorage.get()) {
        if (sessionState.account) queueRuntime.setOwner(sessionState.account.id)
        sessionState.ready = true
        return true
      }
    } else {
      tokenStorage.clear()
    }
  }
  try {
    const response = await mobileApi.wechatLogin(await getLoginCode(), WECHAT_APP_ID)
    if (response.binding_required && response.binding_ticket) {
      uni.setStorageSync(BINDING_TICKET_KEY, response.binding_ticket)
      sessionState.bindingRequired = true
      moveToBinding()
      return false
    }
    if (!response.token || !response.account) throw new Error('登录响应不完整')
    tokenStorage.set(response.token)
    uni.setStorageSync(ACCOUNT_KEY, response.account)
    sessionState.account = response.account
    sessionState.bindingRequired = false
    if (response.bootstrap) applyBootstrap(response.account.id, response.bootstrap)
    else hydrateBootstrap(response.account.id)
    try {
      const bootstrap = await loadBootstrap(response.account.id)
      sessionState.account = bootstrap.account
      uni.setStorageSync(ACCOUNT_KEY, bootstrap.account)
    } catch {
      // 首次登录成功但 bootstrap 暂时失败时，仍保留账号等待联网重试。
    }
    queueRuntime.setOwner(response.account.id)
    sessionState.ready = true
    return true
  } catch (error) {
    sessionState.ready = true
    if (API_MODE === 'real') uni.showToast({ title: error instanceof Error ? error.message : '登录失败', icon: 'none' })
    return false
  }
}

export async function bindExistingAccount(username: string, password: string): Promise<void> {
  const ticket = String(uni.getStorageSync(BINDING_TICKET_KEY) || '')
  if (!ticket) throw new Error('绑定凭证已失效，请重新打开小程序')
  const response = await mobileApi.wechatBind(ticket, username, password)
  if (!response.token || !response.account) throw new Error('账号绑定失败')
  tokenStorage.set(response.token)
  uni.setStorageSync(ACCOUNT_KEY, response.account)
  uni.removeStorageSync(BINDING_TICKET_KEY)
  sessionState.account = response.account
  sessionState.bindingRequired = false
  sessionState.ready = true
  if (response.bootstrap) applyBootstrap(response.account.id, response.bootstrap)
  else hydrateBootstrap(response.account.id)
  try {
    await loadBootstrap(response.account.id)
  } catch {
    if (!response.bootstrap) throw new Error('账号已绑定，但工程数据暂时无法加载，请联网后重试')
  }
  queueRuntime.setOwner(response.account.id)
}

export function signOut(): void {
  queueRuntime.clearOwner()
  selectionStorage.clearOwner()
  clearBootstrapView()
  tokenStorage.clear()
  uni.removeStorageSync(ACCOUNT_KEY)
  sessionState.account = null
  sessionState.ready = false
  void ensureSession()
}

registerAuthExpiredHandler(async (expectedAccountId) => {
  queueRuntime.clearOwner()
  selectionStorage.clearOwner()
  clearBootstrapView()
  tokenStorage.clear()
  uni.removeStorageSync(ACCOUNT_KEY)
  sessionState.account = null
  sessionState.ready = false
  const authenticated = await ensureSession()
  const reconnectedAccount = sessionState.account as Account | null
  const currentAccountId = reconnectedAccount ? String(reconnectedAccount.id) : ''
  if (!authenticated || currentAccountId !== String(expectedAccountId)) return
  queueRuntime.recoverAuthFailures()
  await queueRuntime.resume('manual')
})
