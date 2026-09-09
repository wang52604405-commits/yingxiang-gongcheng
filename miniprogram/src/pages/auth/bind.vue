<script setup lang="ts">
import { themeStyle } from '@/services/theme'
import { computed, ref } from 'vue'
import { onShow, onUnload } from '@dcloudio/uni-app'
import { normalizeInviteCode, peekPendingInvite, rememberPendingInvite } from '@/services/pending-invite'
import PageHeader from '@/components/PageHeader.vue'
import {
  cancelWechatBinding,
  cancelWechatJoin,
  joinProjectWithWechat,
  clearAuthError,
  confirmWechatBinding,
  loginWithAccount,
  quickWechatLogin,
  sessionState,
} from '@/services/auth'

const inviteCode = ref(peekPendingInvite())
const inviteMode = ref(Boolean(inviteCode.value))
const displayName = ref('')
const phone = ref('')
const username = ref('')
const password = ref('')
const formError = ref('')
const pendingAction = ref<'account' | 'bind' | 'quick' | 'join' | ''>('')
const visibleError = computed(() => formError.value || sessionState.error)
const pendingName = computed(() => sessionState.pendingAccount?.username || sessionState.pendingAccount?.display_name || '')

function showInviteForm(): void {
  resetError()
  cancelWechatJoin()
  inviteCode.value = peekPendingInvite() || inviteCode.value
  inviteMode.value = true
}
function showAccountForm(): void {
  resetError()
  cancelWechatJoin()
  const code = normalizeInviteCode(inviteCode.value)
  if (code.length === 10) rememberPendingInvite(code)
  inviteMode.value = false
}
async function joinWithWechat() {
  if (pendingAction.value) return
  resetError()
  inviteCode.value = normalizeInviteCode(inviteCode.value)
  if (inviteCode.value.length !== 10) { formError.value = '请输入完整的 10 位项目邀请码'; return }
  if (!displayName.value.trim()) { formError.value = '请填写实际姓名'; return }
  pendingAction.value = 'join'
  try { await joinProjectWithWechat(inviteCode.value, displayName.value, phone.value) }
  catch { /* Keep the form and show the server's reason for a retry. */ }
  finally { pendingAction.value = '' }
}
onShow(() => {
  const pending = peekPendingInvite()
  if (pending && pending !== inviteCode.value) { inviteCode.value = pending; inviteMode.value = true }
})
onUnload(cancelWechatJoin)

function resetError(): void {
  formError.value = ''
  clearAuthError()
}

async function submitAccount() {
  if (pendingAction.value) return
  resetError()
  if (!username.value.trim() || !password.value) {
    formError.value = '请输入电脑端账号和密码'
    return
  }
  pendingAction.value = 'account'
  try {
    await loginWithAccount(username.value.trim(), password.value)
    password.value = ''
  } catch {
    // 错误由 sessionState 常驻展示，避免一闪而过的 toast。
  } finally {
    pendingAction.value = ''
  }
}

async function bindWechat() {
  if (pendingAction.value) return
  resetError()
  pendingAction.value = 'bind'
  try {
    await confirmWechatBinding()
  } catch {
    // 保留在确认页，可直接重试或返回账号登录。
  } finally {
    pendingAction.value = ''
  }
}

async function quickLogin() {
  if (pendingAction.value) return
  resetError()
  pendingAction.value = 'quick'
  try {
    await quickWechatLogin()
  } catch {
    // 未绑定或网络失败时仍留在账号页，并显示明确原因。
  } finally {
    pendingAction.value = ''
  }
}

function backToAccount(): void {
  resetError()
  password.value = ''
  cancelWechatBinding()
}
</script>

<template>
  <page-meta :page-style="themeStyle" />
  <view class="page-shell no-tabs auth-page">
    <PageHeader title="工程影像" :back="false" />

    <view v-if="sessionState.stage === 'checking'" class="auth-status">
      <view class="loading-spinner" />
      <text class="status-title">正在验证登录</text>
    </view>

    <view v-else class="auth-panel">
      <view class="brand-mark">影</view>

      <template v-if="sessionState.stage === 'bind_wechat'">
        <text class="auth-title">绑定当前微信</text>
        <view class="verified-account">
          <text class="verified-label">已验证账号</text>
          <text class="verified-name">{{ pendingName }}</text>
        </view>
        <view v-if="visibleError" class="error-panel" role="alert">{{ visibleError }}</view>
        <button class="primary-button pressable action-button" :disabled="Boolean(pendingAction)" @tap="bindWechat">
          {{ pendingAction === 'bind' ? '绑定中…' : '绑定当前微信' }}
        </button>
        <button class="text-button pressable" :disabled="Boolean(pendingAction)" @tap="backToAccount">换一个账号</button>
      </template>

      <template v-else-if="inviteMode">
        <text class="auth-title">加入项目</text>
        <text class="auth-hint">填写真实姓名和手机号，由分享人审核</text>
        <text class="field-label first-label">项目邀请码</text>
        <input v-model="inviteCode" class="input invite-code" maxlength="10" placeholder="输入 10 位邀请码" :disabled="Boolean(pendingAction)" @input="resetError" />
        <text class="field-label">姓名</text>
        <input v-model="displayName" class="input" maxlength="60" placeholder="填写真实姓名，便于分享人核实" :disabled="Boolean(pendingAction)" confirm-type="done" @input="resetError" @confirm="joinWithWechat" />
        <text class="field-label">手机号</text>
        <input v-model="phone" class="input" type="number" maxlength="11" placeholder="填写 11 位手机号" :disabled="Boolean(pendingAction)" confirm-type="done" @input="resetError" @confirm="joinWithWechat" />
        <view v-if="visibleError" class="error-panel" role="alert">{{ visibleError }}</view>
        <button class="primary-button pressable action-button" :disabled="Boolean(pendingAction)" @tap="joinWithWechat">{{ pendingAction === 'join' ? '正在提交…' : '微信申请加入' }}</button>
        <button class="text-button pressable" :disabled="Boolean(pendingAction)" @tap="showAccountForm">已有账号登录</button>
      </template>

      <template v-else>
        <text class="auth-title">登录账号</text>
        <text class="field-label first-label">账号</text>
        <input v-model="username" class="input" placeholder="请输入电脑端账号" placeholder-class="input-placeholder" @input="resetError" />
        <text class="field-label">密码</text>
        <input v-model="password" class="input" password placeholder="请输入密码" placeholder-class="input-placeholder" confirm-type="done" @input="resetError" @confirm="submitAccount" />
        <view v-if="visibleError" class="error-panel" role="alert">{{ visibleError }}</view>
        <button class="primary-button pressable action-button" :disabled="Boolean(pendingAction)" @tap="submitAccount">
          {{ pendingAction === 'account' ? '登录中…' : '登录' }}
        </button>
        <button class="secondary-button pressable quick-button" :disabled="Boolean(pendingAction)" @tap="quickLogin">
          {{ pendingAction === 'quick' ? '验证中…' : '微信快捷登录' }}
        </button>
        <button class="text-button pressable" :disabled="Boolean(pendingAction)" @tap="showInviteForm">我有项目邀请码</button>
      </template>
    </view>
  </view>
</template>

<style scoped>
.auth-page { min-height: 100vh; padding-top: 0; }
.auth-panel { width: 100%; max-width: 620rpx; margin: 4vh auto 0; }
.auth-status { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; min-height: 52vh; color: var(--muted); }
.status-title { font-size: 26rpx; }
.brand-mark { display: grid; place-items: center; width: 88rpx; height: 88rpx; margin: 0 auto 22rpx; border-radius: 27rpx; color: #041a1a; background: var(--primary-strong); box-shadow: 0 14rpx 30rpx rgba(45, 185, 170, 0.2); font-size: 38rpx; font-weight: 800; }
.auth-title { display: block; text-align: center; color: var(--text); font-size: 38rpx; font-weight: 700; line-height: 1.3; }
.first-label { margin-top: 34rpx; }
.action-button { margin-top: 30rpx; }
.quick-button { margin-top: 18rpx; }
.error-panel { margin-top: 22rpx; padding: 18rpx 20rpx; border: 1rpx solid rgba(255, 112, 112, 0.28); border-radius: 18rpx; color: #ffb1b1; background: rgba(194, 61, 61, 0.12); font-size: 23rpx; line-height: 1.5; }
.verified-account { margin-top: 34rpx; padding: 24rpx; border: 1rpx solid var(--line); border-radius: 22rpx; text-align: center; background: var(--surface); }
.verified-label { display: block; color: var(--muted); font-size: 22rpx; }
.verified-name { display: block; margin-top: 8rpx; overflow-wrap: anywhere; color: var(--text); font-size: 30rpx; font-weight: 650; }
.text-button { display: flex; align-items: center; justify-content: center; min-height: 76rpx; margin: 14rpx auto 0; padding: 0 24rpx; color: var(--muted); background: transparent; font-size: 24rpx; }
.auth-hint { display:block; margin-top:16rpx; text-align:center; color:var(--muted); font-size:25rpx; }
.invite-code { text-transform:uppercase; letter-spacing:3rpx; }
</style>
