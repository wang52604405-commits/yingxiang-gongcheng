<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import H5TabBar from '@/components/H5TabBar.vue'
import UiIcon from '@/components/UiIcon.vue'
import { sessionState, signOut } from '@/services/auth'
import { queueRuntime } from '@/services/queue-runtime'
import { syncTabBar } from '@/services/navigation'
import { selectionStorage } from '@/stores/selection'
import { formatBytes } from '@/utils/format'

const project = ref(selectionStorage.getProject())
const displayName = computed(() => sessionState.account?.display_name || sessionState.account?.username || '工程资料员')
const initial = computed(() => displayName.value.slice(0, 1))
const uniApi = uni

function showPrivacy() {
  uni.showModal({
    title: '影像与隐私',
    content: '仅在您拍照或选择照片时访问相机和相册。原图上传完成后，本机只保留预览；退出微信会暂停上传。',
    showCancel: false,
  })
}

function confirmSignOut() {
  uni.showModal({ title: '切换账号？', content: '未上传原图仍保留在当前账号队列中。', success: ({ confirm }) => { if (confirm) signOut() } })
}

onShow(() => {
  syncTabBar(4)
  project.value = selectionStorage.getProject()
  queueRuntime.hydrate()
})
</script>

<template>
  <view class="page-shell">
    <AppHeader :project-name="project.name" :online="queueRuntime.state.online" @select-project="uniApi.navigateTo({ url: '/pages/project/select' })" />
    <text class="page-title">我的</text>

    <view class="identity-card">
      <view class="avatar">{{ initial }}</view>
      <view class="identity-copy"><text class="identity-name">{{ displayName }}</text><text class="identity-role">{{ sessionState.account?.username }} · 已绑定微信</text></view>
    </view>

    <view v-if="!queueRuntime.state.online" class="notice offline-notice"><text class="notice-dot" /><text>离线，原图保存在本机</text></view>

    <view class="settings card">
      <button class="setting-row pressable" @tap="uniApi.switchTab({ url: '/pages/queue/index' })">
        <view class="setting-icon"><UiIcon name="storage" :size="18" /></view><text class="setting-title">本机影像</text><text class="setting-value">{{ formatBytes(queueRuntime.queueBytes.value) }}</text>
      </button>
      <button class="setting-row pressable" @tap="showPrivacy">
        <view class="setting-icon"><UiIcon name="shield" :size="18" /></view><text class="setting-title">隐私与权限</text><view class="setting-arrow"><UiIcon name="chevron" :size="17" /></view>
      </button>
    </view>

    <button class="account-button pressable" @tap="confirmSignOut">切换账号</button>
    <text class="version">工程影像 V1.2</text>
    <!-- #ifdef H5 -->
    <H5TabBar :selected="4" :badge="queueRuntime.pendingCount.value" />
    <!-- #endif -->
  </view>
</template>

<style scoped>
.identity-card { display: flex; align-items: center; gap: 22rpx; margin-top: 28rpx; padding: 26rpx; border-radius: 26rpx; color: #fff; background: linear-gradient(135deg, var(--top), var(--primary)); }
.avatar { display: grid; flex: 0 0 auto; place-items: center; width: 88rpx; height: 88rpx; border-radius: 25rpx; background: rgba(255, 255, 255, 0.14); font-size: 36rpx; font-weight: 600; }
.identity-copy { min-width: 0; }
.identity-name { display: block; font-size: 31rpx; font-weight: 700; }
.identity-role { display: block; margin-top: 7rpx; font-size: 22rpx; line-height: 1.45; opacity: 0.78; overflow-wrap: anywhere; }
.offline-notice { margin-top: 24rpx; }
.settings { overflow: hidden; margin-top: 24rpx; }
.setting-row { display: grid; grid-template-columns: 52rpx minmax(0, 1fr) auto; align-items: center; gap: 16rpx; width: 100%; min-height: 92rpx; padding: 16rpx 20rpx; border-bottom: 1rpx solid var(--line); text-align: left; background: transparent; }
.setting-row:last-child { border-bottom: 0; }
.setting-icon { display: grid; place-items: center; width: 50rpx; height: 50rpx; border-radius: 15rpx; color: var(--primary-strong); background: var(--primary-soft); font-size: 27rpx; }
.setting-title { display: block; color: var(--text); font-size: 26rpx; font-weight: 600; }
.setting-value { max-width: 140rpx; overflow: hidden; color: var(--muted); text-align: right; font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
.setting-arrow { display: grid; place-items: center; width: 34rpx; height: 48rpx; color: var(--muted); }
.account-button { display: flex; align-items: center; justify-content: center; min-height: 40px; margin: 22rpx auto 0; padding: 0 24rpx; color: var(--danger); background: transparent; font-size: 24rpx; }
.version { display: block; margin-top: 18rpx; color: var(--muted); text-align: center; font-size: 21rpx; }
</style>
