<script setup lang="ts">
import { computed, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import {
  cancelWechatBinding,
  clearAuthError,
  confirmWechatBinding,
  loginWithAccount,
  quickWechatLogin,
  sessionState,
} from '@/services/auth'

const username = ref('')
const password = ref('')
const formError = ref('')
const pendingAction = ref<'account' | 'bind' | 'quick' | ''>('')
const visibleError = computed(() => formError.value || sessionState.error)
const pendingName = computed(() => sessionState.pendingAccount?.username || sessionState.pendingAccount?.display_name || '')

function resetError(): void {
  formError.value = ''
  clearAuthError()
}

async function submitAccount() {
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
</style>
