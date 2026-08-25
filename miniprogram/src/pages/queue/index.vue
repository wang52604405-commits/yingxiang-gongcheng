<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import H5TabBar from '@/components/H5TabBar.vue'
import { queueRuntime } from '@/services/queue-runtime'
import { STATUS_LABELS } from '@/services/photo-state'
import { syncTabBar } from '@/services/navigation'
import { selectionStorage } from '@/stores/selection'
import { formatBytes } from '@/utils/format'

const project = ref(selectionStorage.getProject())
const photos = computed(() => queueRuntime.state.photos.filter((photo) => photo.status !== 'desktop_imported'))
const uniApi = uni

function openConfirm(clientBatchId: string) {
  uni.navigateTo({ url: `/pages/upload/confirm?batch=${clientBatchId}` })
}

function storageLabel(photo: (typeof queueRuntime.state.photos)[number]) {
  if (photo.original_path) {
    const preview = photo.preview_path ? ` · 预览 ${formatBytes(photo.preview_size)}` : ' · 预览待恢复'
    return `原图待中转 ${formatBytes(photo.original_size)}${preview}`
  }
  return `服务器已保存 · 本机预览 ${formatBytes(photo.preview_size)}`
}

onShow(() => {
  syncTabBar(3)
  project.value = selectionStorage.getProject()
  queueRuntime.hydrate()
  void queueRuntime.resume('app-show')
})
</script>

<template>
  <view class="page-shell">
    <AppHeader :project-name="project.name" :online="queueRuntime.state.online" @select-project="uniApi.navigateTo({ url: '/pages/project/select' })" />
    <view class="title-row">
      <view><text class="page-title">待上传</text><text class="page-subtitle">断网时保存在手机，回到前台联网后继续。</text></view>
      <text class="queue-count">{{ photos.length }} 项</text>
    </view>

    <view class="network-card" :class="{ offline: !queueRuntime.state.online }">
      <view class="network-symbol" />
      <view><text class="network-title">{{ queueRuntime.state.online ? queueRuntime.state.running ? '正在中转原图' : '当前网络正常' : '当前离线' }}</text><text class="network-copy">{{ queueRuntime.state.online ? '回到小程序或网络恢复时自动续传；退出微信后不会后台上传。' : '可以继续拍照，未中转原图会安全留在本机。' }}</text></view>
    </view>

    <view v-if="queueRuntime.failedCount.value" class="retry-bar">
      <text>{{ queueRuntime.failedCount.value }} 张需要重试</text>
      <button class="pressable" @tap="queueRuntime.retryAll">全部重试</button>
    </view>

    <view v-if="photos.length" class="queue-list">
      <view v-for="photo in photos" :key="photo.photo_uuid" class="queue-card card">
        <image v-if="photo.preview_path" class="queue-thumb" :src="photo.preview_path" mode="aspectFill" />
        <view v-else class="queue-thumb preview-waiting">预览</view>
        <view class="queue-copy">
          <text class="queue-title">{{ photo.title }}</text>
          <text class="queue-meta">{{ photo.draft.assignment?.unit_name || photo.draft.assignment?.other_node_name || '等待自动匹配' }}</text>
          <text class="queue-storage">{{ storageLabel(photo) }}</text>
          <view v-if="photo.status === 'uploading'" class="progress-track"><view class="progress-fill" :style="{ transform: `scaleX(${photo.progress / 100})` }" /></view>
          <text v-if="photo.error" class="error-copy">{{ photo.error }}</text>
        </view>
        <view class="queue-actions">
          <text class="status-chip" :class="{ warning: photo.status === 'needs_review', danger: photo.status === 'failed' }">{{ STATUS_LABELS[photo.status] }}</text>
          <button v-if="photo.status === 'failed' && photo.retryable !== false" class="mini-action pressable" @tap="queueRuntime.retry(photo.photo_uuid)">重试</button>
          <button v-if="photo.status === 'needs_review'" class="mini-action confirm pressable" @tap="openConfirm(photo.client_batch_id)">确认</button>
        </view>
      </view>
    </view>
    <view v-else class="empty-state">
      <view class="empty-symbol">✓</view>
      <text class="empty-title">没有待处理影像</text>
      <text class="empty-copy">已上传的照片会等待电脑端自动归档。</text>
    </view>
    <!-- #ifdef H5 -->
    <H5TabBar :selected="3" :badge="queueRuntime.pendingCount.value" />
    <!-- #endif -->
  </view>
</template>

<style scoped>
.title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 20rpx; }
.queue-count { flex: 0 0 auto; margin-top: 10rpx; padding: 10rpx 18rpx; border-radius: 999rpx; color: var(--primary-strong); background: var(--primary-soft); font-size: 22rpx; }
.network-card { display: grid; grid-template-columns: 42rpx 1fr; gap: 14rpx; margin-top: 30rpx; padding: 22rpx; border: 1rpx solid var(--line); border-radius: 22rpx; background: var(--surface); }
.network-card.offline { border-color: rgba(241, 179, 75, 0.45); }
.network-symbol { width: 17rpx; height: 17rpx; margin: 8rpx 0 0 5rpx; border: 3rpx solid rgba(45, 185, 170, 0.24); border-radius: 50%; background: var(--success); }
.network-card.offline .network-symbol { background: var(--warning); border-color: rgba(241, 179, 75, 0.24); }
.network-title { display: block; color: var(--text); font-size: 25rpx; font-weight: 600; }
.network-copy { display: block; margin-top: 6rpx; color: var(--muted); font-size: 21rpx; line-height: 1.5; }
.retry-bar { display: flex; align-items: center; justify-content: space-between; margin-top: 18rpx; padding: 16rpx 20rpx; border-radius: 18rpx; color: var(--danger); background: rgba(255, 107, 102, 0.1); font-size: 23rpx; }
.retry-bar button { display: inline-flex; align-items: center; justify-content: center; min-height: 52rpx; padding: 0 17rpx; border-radius: 15rpx; color: #fff; background: var(--danger); font-size: 22rpx; line-height: 1.25; text-align: center; }
.queue-list { display: grid; gap: 16rpx; margin-top: 24rpx; }
.queue-card { display: grid; grid-template-columns: 112rpx 1fr auto; align-items: center; gap: 18rpx; padding: 14rpx; }
.queue-thumb { width: 112rpx; height: 94rpx; border-radius: 18rpx; background: var(--surface-2); }
.preview-waiting { display: grid; place-items: center; color: var(--muted); font-size: 20rpx; }
.queue-copy { min-width: 0; }
.queue-title { display: block; overflow: hidden; color: var(--text); font-size: 26rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.queue-meta { display: block; overflow: hidden; margin-top: 7rpx; color: var(--muted); font-size: 20rpx; text-overflow: ellipsis; white-space: nowrap; }
.queue-storage { display: block; overflow: hidden; margin-top: 5rpx; color: var(--primary-strong); font-size: 20rpx; text-overflow: ellipsis; white-space: nowrap; }
.progress-track { height: 7rpx; margin-top: 14rpx; overflow: hidden; border-radius: 999rpx; background: var(--surface-2); }
.progress-fill { width: 100%; height: 100%; transform: scaleX(0); transform-origin: left center; background: var(--primary-strong); transition: transform 160ms var(--ease-out); }
.error-copy { display: block; margin-top: 7rpx; color: var(--danger); font-size: 20rpx; }
.queue-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 10rpx; }
.mini-action { display: inline-flex; align-items: center; justify-content: center; min-height: 48rpx; padding: 0 16rpx; border-radius: 14rpx; color: #fff; background: var(--danger); font-size: 21rpx; line-height: 1.25; text-align: center; }
.mini-action.confirm { color: #041a1a; background: var(--primary-strong); }
</style>
