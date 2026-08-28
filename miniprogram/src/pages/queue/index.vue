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
const photos = computed(() => queueRuntime.state.photos.filter((photo) => !['desktop_imported', 'local_deleted'].includes(photo.status)))
const retryableFailures = computed(() => photos.value.filter((photo) => photo.status === 'failed' && photo.retryable !== false).length)
const uniApi = uni
const deletingPhotoId = ref('')

function openConfirm(clientBatchId: string) {
  uni.navigateTo({ url: `/pages/upload/confirm?batch=${clientBatchId}` })
}

function requestDelete(photo: (typeof queueRuntime.state.photos)[number]) {
  if (deletingPhotoId.value) return
  uni.showModal({
    title: '删除失败照片？',
    content: '会删除手机本机的原图、传输图和预览图，无法恢复；服务器已经保存的照片不会删除。',
    confirmText: '删除',
    confirmColor: '#ff6b66',
    success: async ({ confirm }) => {
      if (!confirm) return
      deletingPhotoId.value = photo.photo_uuid
      try {
        await queueRuntime.deleteFailed(photo.photo_uuid)
        uni.showToast({ title: '已从本机删除', icon: 'success' })
      } catch (error) {
        uni.showModal({ title: '删除失败', content: error instanceof Error ? error.message : '请稍后重试', showCancel: false })
      } finally {
        deletingPhotoId.value = ''
      }
    },
  })
}

function storageLabel(photo: (typeof queueRuntime.state.photos)[number]) {
  if (photo.transfer_path) {
    const preview = photo.preview_path ? ` · 预览 ${formatBytes(photo.preview_size)}` : ' · 预览待恢复'
    return `待传图 ${formatBytes(Number(photo.transfer_size || 0))}${preview}`
  }
  if (photo.original_path) {
    return `原始照片已保存 · 正在生成传输图`
  }
  if (!photo.preview_path) return '归档图已上传 · 预览自动恢复中'
  return `预览 ${formatBytes(photo.preview_size)}`
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
      <text class="page-title">待上传</text>
      <text class="queue-count">{{ photos.length }} 项</text>
    </view>

    <view v-if="!queueRuntime.state.online" class="network-card offline">
      <view class="network-symbol" />
      <text class="network-title">离线，待传图已保存在本机</text>
    </view>

    <view v-if="retryableFailures" class="retry-bar">
      <text>{{ retryableFailures }} 张需要重试</text>
      <button class="pressable" @tap="queueRuntime.retryAll">全部重试</button>
    </view>

    <view v-if="photos.length" class="queue-list">
      <view v-for="photo in photos" :key="photo.photo_uuid" class="queue-card card">
        <image v-if="photo.preview_path" class="queue-thumb" :src="photo.preview_path" mode="aspectFill" />
        <view v-else class="queue-thumb preview-waiting">预览</view>
        <view class="queue-copy">
          <view class="queue-top"><text class="queue-title">{{ photo.title }}</text><text class="status-chip" :class="{ warning: photo.status === 'needs_review', danger: photo.status === 'failed' }">{{ STATUS_LABELS[photo.status] }}</text></view>
          <text class="queue-meta">{{ photo.draft.assignment?.unit_name || photo.draft.assignment?.other_node_name || '等待自动匹配' }}</text>
          <text class="queue-storage">{{ storageLabel(photo) }}</text>
          <view v-if="photo.status === 'uploading'" class="progress-track"><view class="progress-fill" :style="{ transform: `scaleX(${photo.progress / 100})` }" /></view>
          <text v-if="photo.error" class="error-copy">{{ photo.error }}</text>
          <view v-if="photo.status === 'failed' || photo.status === 'needs_review'" class="queue-actions">
            <button v-if="photo.failure_code === 'ARCHIVE_INFO_REQUIRED'" class="mini-action confirm pressable" @tap="openConfirm(photo.client_batch_id)">完善信息</button>
            <button v-if="queueRuntime.canManuallyRetry(photo.photo_uuid)" class="mini-action pressable" @tap="queueRuntime.retry(photo.photo_uuid)">{{ photo.retryable === false ? '权限恢复后重试' : '重试' }}</button>
            <button v-if="photo.status === 'needs_review'" class="mini-action confirm pressable" @tap="openConfirm(photo.client_batch_id)">确认</button>
            <button v-if="photo.status === 'failed'" class="mini-action delete pressable" :disabled="Boolean(deletingPhotoId)" :loading="deletingPhotoId === photo.photo_uuid" @tap="requestDelete(photo)">删除</button>
          </view>
        </view>
      </view>
    </view>
    <view v-else class="empty-state">
      <view class="empty-symbol">✓</view>
      <text class="empty-title">暂无待上传影像</text>
    </view>
    <!-- #ifdef H5 -->
    <H5TabBar :selected="3" :badge="queueRuntime.pendingCount.value" />
    <!-- #endif -->
  </view>
</template>

<style scoped>
.title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 20rpx; }
.queue-count { flex: 0 0 auto; margin-top: 10rpx; padding: 10rpx 18rpx; border-radius: 999rpx; color: var(--primary-strong); background: var(--primary-soft); font-size: 22rpx; }
.network-card { display: grid; grid-template-columns: 42rpx 1fr; align-items: center; gap: 14rpx; margin-top: 24rpx; padding: 18rpx 22rpx; border: 1rpx solid var(--line); border-radius: 20rpx; background: var(--surface); }
.network-card.offline { border-color: rgba(241, 179, 75, 0.45); }
.network-symbol { width: 17rpx; height: 17rpx; margin: 8rpx 0 0 5rpx; border: 3rpx solid rgba(45, 185, 170, 0.24); border-radius: 50%; background: var(--success); }
.network-card.offline .network-symbol { background: var(--warning); border-color: rgba(241, 179, 75, 0.24); }
.network-title { display: block; color: var(--text); font-size: 25rpx; font-weight: 600; }
.retry-bar { display: flex; align-items: center; justify-content: space-between; margin-top: 18rpx; padding: 16rpx 20rpx; border-radius: 18rpx; color: var(--danger); background: rgba(255, 107, 102, 0.1); font-size: 23rpx; }
.retry-bar button { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; padding: 0 20rpx; border-radius: 15rpx; color: #fff; background: var(--danger); font-size: 23rpx; line-height: 1.25; text-align: center; }
.queue-list { display: grid; gap: 18rpx; margin-top: 24rpx; }
.queue-card { display: grid; grid-template-columns: 104rpx minmax(0, 1fr); align-items: start; gap: 16rpx; padding: 18rpx; }
.queue-thumb { width: 104rpx; height: 96rpx; border-radius: 17rpx; background: var(--surface-2); }
.preview-waiting { display: grid; place-items: center; color: var(--muted); font-size: 20rpx; }
.queue-copy { min-width: 0; }
.queue-top { display: flex; align-items: flex-start; justify-content: space-between; min-width: 0; gap: 12rpx; }
.queue-title { display: block; flex: 1; min-width: 0; overflow: hidden; color: var(--text); font-size: 26rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.queue-meta { display: block; overflow: hidden; margin-top: 8rpx; color: var(--muted); font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
.queue-storage { display: block; overflow: hidden; margin-top: 6rpx; color: var(--primary-strong); font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
.progress-track { height: 7rpx; margin-top: 14rpx; overflow: hidden; border-radius: 999rpx; background: var(--surface-2); }
.progress-fill { width: 100%; height: 100%; transform: scaleX(0); transform-origin: left center; background: var(--primary-strong); transition: transform 160ms var(--ease-out); }
.error-copy { display: block; margin-top: 7rpx; color: var(--danger); font-size: 22rpx; }
.queue-actions { display: flex; justify-content: flex-end; gap: 10rpx; margin-top: 14rpx; }
.mini-action { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; padding: 0 22rpx; border-radius: 15rpx; color: #fff; background: var(--danger); font-size: 23rpx; line-height: 1.25; text-align: center; }
.mini-action.confirm { color: #041a1a; background: var(--primary-strong); }
.mini-action.delete { border: 1rpx solid rgba(255, 107, 102, 0.58); color: var(--danger); background: rgba(255, 107, 102, 0.08); }
</style>
