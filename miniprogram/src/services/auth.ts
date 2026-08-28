import { reactive } from 'vue'
import { API_MODE, WECHAT_APP_ID } from '@/config/env'
import { mobileApi, type AuthResponse } from '@/api/mobile'
import { ApiError, tokenStorage } from '@/api/client'
import type { Account } from '@/types/domain'
import { applyBootstrap, clearBootstrapView, hydrateBootstrap, loadBootstrap } from '@/stores/bootstrap'
import { queueRuntime } from '@/services/queue-runtime'
import { selectionStorage } from '@/stores/selection'
import { registerAuthExpiredHandler } from './auth-expiry-coordinator'
import { consumePendingInvite, peekPendingInvite } from './pending-invite'

const ACCOUNT_KEY = 'engineering-image:account:v1'
const AUTH_ROUTE = 'pages/auth/bind'
const HOME_URL = '/pages/home/index'
const JOIN_PROJECT_ROUTE = 'pages/project/join'

export type AuthStage = 'checking' | 'account_login' | 'bind_wechat' | 'authenticated'

const storedAccount = (uni.getStorageSync(ACCOUNT_KEY) || null) as Account | null

export const sessionState = reactive<{
  ready: boolean
  account: Account | null
  pendingAccount: Account | null
  bindingIntent: string
  stage: AuthStage
  error: string
}>({
  ready: false,
  account: storedAccount,
  pendingAccount: null,
  bindingIntent: '',
  stage: tokenStorage.get() && storedAccount ? 'checking' : 'account_login',
  error: '',
})

function currentRoute(): string {
  const pages = typeof getCurrentPages === 'function' ? getCurrentPages() : []
  const page = pages.length ? pages[pages.length - 1] : undefined
  return page?.route || ''
}

function moveToLogin(): void {
  if (currentRoute() === AUTH_ROUTE) return
  setTimeout(() => {
    if (currentRoute() !== AUTH_ROUTE) uni.reLaunch({ url: `/${AUTH_ROUTE}` })
  }, 0)
}

function moveToHome(): void {
  setTimeout(() => {
    const route = currentRoute()
    const inviteCode = peekPendingInvite()
    if (inviteCode && route !== JOIN_PROJECT_ROUTE) {
      consumePendingInvite()
      uni.reLaunch({ url: `/${JOIN_PROJECT_ROUTE}?code=${encodeURIComponent(inviteCode)}` })
      return
    }
    if (!route || route === AUTH_ROUTE) uni.reLaunch({ url: HOME_URL })
  }, 0)
}

function getLoginCode(): Promise<string> {
  if (API_MODE === 'mock') return Promise.resolve('mock-code')
  return new Promise((resolve, reject) => {
    uni.login({
      provider: 'weixin',
      success: (result) => result.code ? resolve(result.code) : reject(new Error('微信登录凭证获取失败')),
      fail: reject,
    })
  })
}

function messageOf(error: unknown, fallback = '登录失败，请稍后重试'): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function clearVerifiedSession(): void {
  queueRuntime.clearOwner()
  selectionStorage.clearOwner()
  clearBootstrapView()
  tokenStorage.clear()
  uni.removeStorageSync(ACCOUNT_KEY)
  sessionState.account = null
}

function resetPendingBinding(): void {
  sessionState.pendingAccount = null
  sessionState.bindingIntent = ''
}

function showAccountLogin(message = ''): void {
  clearVerifiedSession()
  resetPendingBinding()
  sessionState.stage = 'account_login'
  sessionState.ready = true
  sessionState.error = message
  moveToLogin()
}

async function acceptAuthenticatedResponse(response: AuthResponse): Promise<void> {
  if (!response.token || !response.account || !response.bootstrap) {
    throw new Error('服务器登录响应不完整，请稍后重试')
  }
  try {
    tokenStorage.set(response.token)
    uni.setStorageSync(ACCOUNT_KEY, response.account)
    applyBootstrap(response.account.id, response.bootstrap)
  } catch (error) {
    clearVerifiedSession()
    throw error
  }
  sessionState.account = response.account
  resetPendingBinding()
  sessionState.stage = 'authenticated'
  sessionState.ready = true
  sessionState.error = ''
  queueRuntime.setOwner(response.account.id)
  queueRuntime.recoverAuthFailures()
  void queueRuntime.resume('manual')
  moveToHome()
}

export function clearAuthError(): void {
  sessionState.error = ''
}

export async function ensureSession(): Promise<boolean> {
  const token = tokenStorage.get()
  if (
    !token
    && !sessionState.account
    && sessionState.stage === 'bind_wechat'
    && sessionState.bindingIntent
    && sessionState.pendingAccount
  ) {
    // 账号已验证但尚未确认绑定时，切后台再回来仍应停留在确认页。
    // bindingIntent 只保存在当前进程内，彻底退出后会自然要求重新验证账号。
    sessionState.ready = true
    moveToLogin()
    return false
  }

  sessionState.error = ''
  if (!token || !sessionState.account) {
    showAccountLogin()
    return false
  }

  sessionState.stage = 'checking'
  hydrateBootstrap(sessionState.account.id)
  try {
    const bootstrap = await loadBootstrap(sessionState.account.id)
    sessionState.account = bootstrap.account
    uni.setStorageSync(ACCOUNT_KEY, bootstrap.account)
  } catch (error) {
    const unauthorized = error instanceof ApiError
      && (error.statusCode === 401 || ['unauthorized', 'token_expired'].includes(error.code))
    if (unauthorized) {
      showAccountLogin('登录已过期，请重新登录')
      return false
    }
    // 已验证过的本地会话在断网时仍可查看本账号缓存和待传原图。
    sessionState.stage = 'authenticated'
    sessionState.ready = true
    queueRuntime.setOwner(sessionState.account.id)
    moveToHome()
    return true
  }

  sessionState.stage = 'authenticated'
  sessionState.ready = true
  queueRuntime.setOwner(sessionState.account.id)
  moveToHome()
  return true
}

export async function loginWithAccount(username: string, password: string): Promise<void> {
  sessionState.error = ''
  try {
    const code = await getLoginCode()
    const response = await mobileApi.accountLogin(username, password, code, WECHAT_APP_ID)
    if (!response.account || !response.binding_intent) throw new Error('账号验证响应不完整，请重新登录')
    // 第一步只保留短时绑定意图，不写 token、账号或 bootstrap。
    sessionState.pendingAccount = response.account
    sessionState.bindingIntent = response.binding_intent
    sessionState.stage = 'bind_wechat'
    sessionState.ready = true
  } catch (error) {
    sessionState.error = messageOf(error, '账号登录失败')
    throw error
  }
}

export async function confirmWechatBinding(): Promise<void> {
  sessionState.error = ''
  try {
    if (!sessionState.bindingIntent) throw new Error('绑定凭证已失效，请重新登录账号')
    const response = await mobileApi.wechatBindConfirm(sessionState.bindingIntent)
    await acceptAuthenticatedResponse(response)
  } catch (error) {
    sessionState.error = messageOf(error, '微信绑定失败')
    throw error
  }
}

export async function quickWechatLogin(): Promise<void> {
  sessionState.error = ''
  try {
    const response = await mobileApi.wechatLogin(await getLoginCode(), WECHAT_APP_ID)
    if (response.binding_required || !response.token) {
      throw new Error('当前微信尚未绑定账号，请先使用账号密码登录')
    }
    await acceptAuthenticatedResponse(response)
  } catch (error) {
    sessionState.error = messageOf(error, '微信快捷登录失败')
    throw error
  }
}

export function cancelWechatBinding(): void {
  resetPendingBinding()
  sessionState.stage = 'account_login'
  sessionState.error = ''
}

export function signOut(): void {
  showAccountLogin()
}

registerAuthExpiredHandler(async () => {
  showAccountLogin('登录已过期，请重新登录')
})
