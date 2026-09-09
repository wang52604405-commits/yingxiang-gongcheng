import { clearJoinRequest, rememberJoinRequest, validateJoinApplicant } from './project-join-request'
import { reactive } from 'vue'
import { API_MODE, WECHAT_APP_ID } from '@/config/env'
import { mobileApi, type AuthResponse } from '@/api/mobile'
import { ApiError, tokenStorage } from '@/api/client'
import type { Account } from '@/types/domain'
import { applyBootstrap, clearBootstrapView, hydrateBootstrap, loadBootstrap } from '@/stores/bootstrap'
import { queueRuntime } from '@/services/queue-runtime'
import { selectionStorage } from '@/stores/selection'
import { registerAuthExpiredHandler } from './auth-expiry-coordinator'
import { consumePendingInvite, peekPendingInvite, normalizeInviteCode, rememberPendingInvite, isDiscardedInviteEntry, clearDiscardedInviteEntry, invalidatePendingInvite, isInvalidInviteError, takeLaunchInviteNavigation } from './pending-invite'

const ACCOUNT_KEY = 'engineering-image:account:v1'
const AUTH_ROUTE = 'pages/auth/bind'
const HOME_URL = '/pages/home/index'
const JOIN_PROJECT_ROUTE = 'pages/project/join'
let authAttempt = 0

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
  const attempt = authAttempt
  setTimeout(() => {
    if (attempt !== authAttempt || sessionState.stage === 'authenticated') return
    if (currentRoute() !== AUTH_ROUTE) uni.reLaunch({ url: `/${AUTH_ROUTE}` })
  }, 0)
}

function moveToHome(requestToOpen = ''): void {
  const accountId = sessionState.account?.id
  const token = tokenStorage.get()
  setTimeout(() => {
    if (sessionState.stage !== 'authenticated' || sessionState.account?.id !== accountId || tokenStorage.get() !== token) return
    const route = currentRoute()
    const inviteCode = peekPendingInvite()
    const freshInvite = takeLaunchInviteNavigation()
    if (inviteCode && (route !== JOIN_PROJECT_ROUTE || freshInvite === inviteCode)) {
      uni.reLaunch({ url: `/${JOIN_PROJECT_ROUTE}?code=${encodeURIComponent(inviteCode)}` })
      return
    }
    if (route === JOIN_PROJECT_ROUTE && !inviteCode && isDiscardedInviteEntry()) { clearDiscardedInviteEntry(); uni.reLaunch({ url: HOME_URL }); return }
    const requestId = requestToOpen
    if (requestId && (!route || route === AUTH_ROUTE)) { uni.reLaunch({ url: `/pages/project/request-status?id=${encodeURIComponent(requestId)}` }); return }
    if (!route || route === AUTH_ROUTE) { clearDiscardedInviteEntry(); uni.reLaunch({ url: HOME_URL }) }
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

async function acceptAuthenticatedResponse(response: AuthResponse, joinedInvite = '', canAccept: () => boolean = () => true): Promise<void> {
  if (!canAccept()) throw new Error('登录操作已取消，请重试')
  if (!response.token || !response.account || !response.bootstrap) {
    throw new Error('服务器登录响应不完整，请稍后重试')
  }
  try {
    tokenStorage.set(response.token)
    uni.setStorageSync(ACCOUNT_KEY, response.account)
    if (joinedInvite && response.project && !response.pending_approval) applyBootstrap(response.account.id, response.bootstrap, response.project.id)
    else applyBootstrap(response.account.id, response.bootstrap)
  } catch (error) {
    clearVerifiedSession()
    throw error
  }
  sessionState.account = response.account
  resetPendingBinding()
  sessionState.stage = 'authenticated'
  sessionState.ready = true
  sessionState.error = ''
  if (joinedInvite && response.join_request && response.join_request.status !== 'approved') rememberJoinRequest(response.account.id, response.join_request.id)
  else if (joinedInvite) clearJoinRequest(response.account.id)
  if (joinedInvite && peekPendingInvite() === joinedInvite) consumePendingInvite()
  queueRuntime.setOwner(response.account.id)
  queueRuntime.recoverAuthFailures()
  void queueRuntime.resume('manual')
  moveToHome(joinedInvite && response.join_request && response.join_request.status !== 'approved' ? response.join_request.id : '')
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

  const accountId = sessionState.account.id
  const attempt = authAttempt
  const stillCurrent = () => authAttempt === attempt && tokenStorage.get() === token && sessionState.account?.id === accountId
  sessionState.stage = 'checking'
  hydrateBootstrap(accountId)
  try {
    const bootstrap = await loadBootstrap(accountId, '', stillCurrent)
    if (!stillCurrent()) return false
    sessionState.account = bootstrap.account
    uni.setStorageSync(ACCOUNT_KEY, bootstrap.account)
  } catch (error) {
    if (!stillCurrent()) return false
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
  const attempt = ++authAttempt
  sessionState.error = ''
  try {
    const code = await getLoginCode()
    if (attempt !== authAttempt) throw new Error('登录操作已取消，请重试')
    const response = await mobileApi.accountLogin(username, password, code, WECHAT_APP_ID)
    if (attempt !== authAttempt) throw new Error('登录操作已取消，请重试')
    if (!response.account || !response.binding_intent) throw new Error('账号验证响应不完整，请重新登录')
    // 第一步只保留短时绑定意图，不写 token、账号或 bootstrap。
    sessionState.pendingAccount = response.account
    sessionState.bindingIntent = response.binding_intent
    sessionState.stage = 'bind_wechat'
    sessionState.ready = true
  } catch (error) {
    if (attempt === authAttempt) sessionState.error = messageOf(error, '账号登录失败')
    throw error
  }
}

export async function confirmWechatBinding(): Promise<void> {
  const attempt = ++authAttempt
  const intent = sessionState.bindingIntent
  const stillCurrent = () => attempt === authAttempt && sessionState.bindingIntent === intent
  sessionState.error = ''
  try {
    if (!intent) throw new Error('绑定凭证已失效，请重新登录账号')
    const response = await mobileApi.wechatBindConfirm(intent)
    await acceptAuthenticatedResponse(response, '', stillCurrent)
  } catch (error) {
    if (attempt === authAttempt) sessionState.error = messageOf(error, '微信绑定失败')
    throw error
  }
}

export async function quickWechatLogin(): Promise<void> {
  const attempt = ++authAttempt
  const stillCurrent = () => attempt === authAttempt
  sessionState.error = ''
  try {
    const code = await getLoginCode()
    if (!stillCurrent()) throw new Error('登录操作已取消，请重试')
    const response = await mobileApi.wechatLogin(code, WECHAT_APP_ID)
    if (!stillCurrent()) throw new Error('登录操作已取消，请重试')
    if (response.binding_required || !response.token) {
      throw new Error('当前微信尚未绑定账号，请使用项目邀请码加入，或登录已有账号')
    }
    await acceptAuthenticatedResponse(response, '', stillCurrent)
  } catch (error) {
    if (attempt === authAttempt) sessionState.error = messageOf(error, '微信快捷登录失败')
    throw error
  }
}

export function cancelWechatJoin(): void { authAttempt += 1 }

export async function joinProjectWithWechat(inviteCode: string, displayName: string, phone: string): Promise<void> {
  const invite = normalizeInviteCode(inviteCode)
  const name = displayName.trim()
  const attempt = ++authAttempt
  sessionState.error = ''
  try {
    if (invite.length !== 10) throw new Error('请输入完整的 10 位项目邀请码')
    const validationError = validateJoinApplicant(name, phone)
    if (validationError) throw new Error(validationError)
    rememberPendingInvite(invite)
    const code = await getLoginCode()
    const stillCurrent = () => attempt === authAttempt && peekPendingInvite() === invite
    if (!stillCurrent()) throw new Error('加入操作已取消，请重新确认邀请码')
    const response = await mobileApi.wechatJoin(invite, name, phone.trim(), code, WECHAT_APP_ID)
    if (!stillCurrent()) throw new Error('加入操作已取消，请重新确认邀请码')
    if (!response.join_request && !(response.already_member && response.project?.id)) throw new Error('申请响应不完整，请重试')
    if (response.join_request && response.account && response.join_request.applicant_account_id !== String(response.account.id)) throw new Error('申请账号不匹配，请重新登录')
    await acceptAuthenticatedResponse(response, invite, stillCurrent)
  } catch (error) {
    if (attempt === authAttempt) {
      if (isInvalidInviteError(error)) invalidatePendingInvite(invite)
      sessionState.error = messageOf(error, '加入项目失败，请稍后重试')
    }
    throw error
  }
}

export function cancelWechatBinding(): void {
  authAttempt += 1
  resetPendingBinding()
  sessionState.stage = 'account_login'
  sessionState.error = ''
}

export function signOut(): void {
  authAttempt += 1
  showAccountLogin()
}

registerAuthExpiredHandler(async () => {
  authAttempt += 1
  showAccountLogin('登录已过期，请重新登录')
})
