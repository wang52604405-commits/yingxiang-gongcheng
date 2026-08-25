<script setup lang="ts">
import { ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import { bindExistingAccount } from '@/services/auth'

const username = ref('')
const password = ref('')
const submitting = ref(false)

async function submit() {
  if (!username.value.trim() || !password.value) {
    uni.showToast({ title: '请填写电脑端账号和密码', icon: 'none' })
    return
  }
  submitting.value = true
  try {
    await bindExistingAccount(username.value.trim(), password.value)
    uni.reLaunch({ url: '/pages/home/index' })
  } catch (error) {
    uni.showModal({ title: '登录/绑定失败', content: error instanceof Error ? error.message : '请检查账号和密码', showCancel: false })
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <view class="page-shell no-tabs bind-page">
    <PageHeader title="工程影像" subtitle="连接桌面端账号" :back="false" />
    <view class="brand-mark">影</view>
    <text class="bind-title">登录桌面端账号</text>
    <text class="bind-copy">输入你在桌面端使用的账号和密码即可拉取该账号下的工程项目。一个桌面端账号最多绑定一个微信账号，绑定后无需重复输入。</text>

    <text class="field-label">账号</text>
    <input v-model="username" class="input" placeholder="请输入电脑端账号" placeholder-class="input-placeholder" />
    <text class="field-label">密码</text>
    <input v-model="password" class="input" password placeholder="请输入密码" placeholder-class="input-placeholder" confirm-type="done" @confirm="submit" />
    <button class="primary-button pressable submit" :disabled="submitting" @tap="submit">{{ submitting ? '正在绑定…' : '登录并进入小程序' }}</button>

    <view class="notice privacy-note"><text class="notice-dot" /><text>照片只在您主动选择时处理。原图会安全中转；服务器确认保存后，本机只保留不超过 100KB 的预览。</text></view>
  </view>
</template>

<style scoped>
.bind-page { padding-top: 0; }
.brand-mark { display: grid; place-items: center; width: 96rpx; height: 96rpx; margin: 0 auto 24rpx; border-radius: 29rpx; color: #041a1a; background: var(--primary-strong); box-shadow: 0 16rpx 34rpx rgba(45, 185, 170, 0.22); font-size: 41rpx; font-weight: 800; }
.bind-title { display: block; text-align: center; font-size: 40rpx; font-weight: 700; }
.bind-copy { display: block; max-width: 560rpx; margin: 12rpx auto 26rpx; color: var(--muted); text-align: center; font-size: 24rpx; line-height: 1.6; }
.bind-copy + .field-label { margin-top: 0; }
.submit { margin-top: 34rpx; }
.privacy-note { margin-top: 28rpx; }
</style>
