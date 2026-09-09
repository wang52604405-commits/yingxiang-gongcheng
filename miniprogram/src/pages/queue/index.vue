<script setup lang="ts">
import { themeStyle } from '@/services/theme'
import DeletePasswordDialog from '@/components/DeletePasswordDialog.vue'
import { photoActions } from '@/services/photo-actions'
import type { LocalPhoto } from '@/types/domain'
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
const activeFilter = ref('all')
const projectPhotos = computed(() => queueRuntime.state.photos.filter((photo) => photo.status !== 'local_deleted' && !photo.deleted_at && String(photo.draft.project_id) === String(project.value.id)))
const filters = [
  { key: 'all', label: '全部' }, { key: 'pending', label: '待上传' },
  { key: 'saved', label: '已上传' }, { key: 'completed', label: '已完成' }, { key: 'attention', label: '需处理' },
]
function matchesFilter(status: string, filter: string) {
  if (filter === 'pending') return ['local_ready', 'uploading'].includes(status)
  if (filter === 'saved') return ['server_saved', 'analyzing', 'needs_review', 'desktop_pending'].includes(status)
  if (filter === 'completed') return status === 'desktop_imported'
  if (filter === 'attention') return ['failed', 'needs_review'].includes(status)
  return true
}
const photos = computed(() => projectPhotos.value.filter((photo) => matchesFilter(photo.status, activeFilter.value)))
function filterCount(filter: string) { return projectPhotos.value.filter((photo) => matchesFilter(photo.status, filter)).length }
function statusLabel(status: keyof typeof STATUS_LABELS) {
  return status === 'desktop_pending' ? '已上传 · 待电脑归档' : status === 'desktop_imported' ? '已完成' : STATUS_LABELS[status]
}
const retryableFailures = computed(() => projectPhotos.value.filter((photo) => photo.status === 'failed' && photo.retryable !== false).length)
const emptyTitle = computed(() => activeFilter.value === 'all' ? '暂无同步记录' : '暂无' + (filters.find((item) => item.key === activeFilter.value)?.label || '') + '照片')
function retryProjectFailures() {
  for (const photo of projectPhotos.value.filter((item) => item.status === 'failed' && item.retryable !== false)) void queueRuntime.retry(photo.photo_uuid)
}
const uniApi = uni
const deletingPhotoId = ref('')

function openConfirm(clientBatchId: string) {
  uni.navigateTo({ url: `/pages/upload/confirm?batch=${clientBatchId}` })
}

const deleteTarget = ref<LocalPhoto | null>(null)
const deleteError = ref('')
function requestDelete(photo: LocalPhoto) { if (!deletingPhotoId.value) { deleteTarget.value = photo; deleteError.value = '' } }
async function confirmDelete(password: string) {
  const photo = deleteTarget.value
  if (!photo || deletingPhotoId.value) return
  const owner = selectionStorage.getOwner()
  deletingPhotoId.value = photo.photo_uuid
  try {
    await photoActions.verifyPassword(photo.draft.project_id,password)
    if (owner !== selectionStorage.getOwner() || String(project.value.id) !== photo.draft.project_id) return
    await queueRuntime.deleteFailed(photo.photo_uuid)
    deleteTarget.value = null
    uni.showToast({title:'已从本机删除',icon:'success'})
  } catch(error) { deleteError.value = error instanceof Error ? error.message : '删除失败' }
  finally { deletingPhotoId.value = '' }
}

function storageLabel(photo: (typeof queueRuntime.state.photos)[number]) {
  if (photo.status === 'desktop_imported') return '电脑端已接收并归档'
  if (['server_saved', 'analyzing', 'needs_review', 'desktop_pending'].includes(photo.status)) return photo.status === 'needs_review' ? '照片已上传，请确认归档信息' : '照片已上传，电脑端同步后完成归档'
  if (photo.transfer_path) {
    const preview = photo.preview_path ? ` · 预览 ${formatBytes(photo.preview_size)}` : ' · 上传后生成预览'
    return `待传图 ${formatBytes(Number(photo.transfer_size || 0))}${preview}`
  }
  if (photo.original_path) {
    const phase = photo.status === 'uploading' ? '正在上传' : '等待上传'
    return `原始照片 ${formatBytes(photo.original_size)} · ${phase}`
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
  <page-meta :page-style="themeStyle" />
  <view class="page-shell">
    <AppHeader :project-name="project.name" :online="queueRuntime.state.online" @select-project="uniApi.navigateTo({ url: '/pages/project/select' })" />
    <view class="title-row">
      <text class="page-title">同步记录</text>
      <text class="queue-count">{{ projectPhotos.length }} 项</text>
    </view>

    <scroll-view scroll-x class="filter-scroll"><view class="filter-row"><button v-for="item in filters" :key="item.key" class="filter-button pressable" :class="{ active: activeFilter === item.key }" @tap="activeFilter = item.key">{{ item.label }} {{ filterCount(item.key) }}</button></view></scroll-view>

    <view v-if="!queueRuntime.state.online" class="network-card offline">
      <view class="network-symbol" />
      <text class="network-title">离线，待传图已保存在本机</text>
    </view>

    <view v-if="retryableFailures" class="retry-bar">
      <text>{{ retryableFailures }} 张需要重试</text>
      <button class="pressable" @tap="retryProjectFailures">全部重试</button>
    </view>

    <view v-if="photos.length" class="queue-list">
      <view v-for="photo in photos" :key="photo.photo_uuid" class="queue-card card">
        <image v-if="photo.preview_path || photo.original_path" class="queue-thumb" :src="photo.preview_path || photo.original_path" mode="aspectFill" />
        <view v-else class="queue-thumb preview-waiting">预览</view>
        <view class="queue-copy">
          <view class="queue-top"><text class="queue-title">{{ photo.title }}</text><text class="status-chip" :class="{ warning: photo.status === 'needs_review', danger: photo.status === 'failed' }">{{ statusLabel(photo.status) }}</text></view>
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
      <text class="empty-title">{{ emptyTitle }}</text>
    </view>
    <!-- #ifdef H5 -->
    <H5TabBar :selected="3" :badge="queueRuntime.pendingCount.value" />
    <!-- #endif -->
    <DeletePasswordDialog :visible="Boolean(deleteTarget)" :busy="Boolean(deletingPhotoId)" :error="deleteError" message="验证项目删除密码后，删除本机失败照片；服务器已保存的照片不受影响。" @close="deleteTarget = null" @confirm="confirmDelete" />
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
.filter-scroll { width: 100%; margin-top: 18rpx; white-space: nowrap; }
.filter-row { display: flex; gap: 10rpx; }
.filter-button { flex-shrink: 0; display: inline-flex; align-items: center; min-height: 44px; padding: 0 20rpx; border: 1rpx solid var(--line); border-radius: 18rpx; color: var(--muted); background: var(--surface); font-size: 23rpx; }
.filter-button.active { color: var(--primary-strong); border-color: var(--primary-strong); background: var(--primary-soft); }
.status-chip { max-width: 210rpx; white-space: normal; text-align: right; }
</style>
