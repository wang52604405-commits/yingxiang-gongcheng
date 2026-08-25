<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { queueRuntime } from '@/services/queue-runtime'
import { STATUS_LABELS } from '@/services/photo-state'
import type { CloudPhoto, LocalPhoto } from '@/types/domain'
import { formatBytes } from '@/utils/format'

const photoId = ref('')
const local = ref<LocalPhoto | null>(null)
const cloud = ref<CloudPhoto | null>(null)
const loading = ref(true)
const imageUrl = computed(() => local.value?.preview_path || cloud.value?.image_url || cloud.value?.thumb_url || '')
const title = computed(() => local.value?.title || cloud.value?.title || '影像详情')
const status = computed(() => local.value?.status || cloud.value?.status)

async function load() {
  queueRuntime.hydrate()
  local.value = queueRuntime.state.photos.find((photo) => photo.photo_uuid === photoId.value) || null
  if (!local.value) {
    try {
      const response = await mobileApi.photo(photoId.value)
      cloud.value = response.photo
    } catch (error) {
      uni.showModal({ title: '影像读取失败', content: error instanceof Error ? error.message : '请稍后重试', showCancel: false })
    }
  }
  loading.value = false
}

function preview() {
  if (imageUrl.value) uni.previewImage({ current: imageUrl.value, urls: [imageUrl.value] })
}

onLoad((query) => {
  photoId.value = String(query?.id || '')
  void load()
})
</script>

<template>
  <view class="page-shell no-tabs detail-page">
    <PageHeader :title="title" subtitle="影像详情" />
    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">正在读取影像</text></view>
    <template v-else-if="local || cloud">
      <button class="photo-preview pressable" @tap="preview">
        <image v-if="imageUrl" :src="imageUrl" mode="aspectFit" />
        <view v-else class="preview-placeholder">暂无可查看缩略图</view>
      </button>
      <view class="detail-card card">
        <view class="detail-row"><text>题名</text><text>{{ title }}</text></view>
        <view class="detail-row"><text>日期</text><text>{{ local?.photo_date || cloud?.photo_date }}</text></view>
        <view class="detail-row"><text>归档位置</text><text>{{ local?.draft.assignment?.unit_name || local?.draft.assignment?.other_node_name || cloud?.unit_name || cloud?.other_node_name || '待确认' }}</text></view>
        <view v-if="local?.draft.assignment?.process_name || cloud?.process_name" class="detail-row"><text>工序</text><text>{{ local?.draft.assignment?.process_name || cloud?.process_name }}</text></view>
        <view class="detail-row"><text>状态</text><text class="status-value">{{ status ? STATUS_LABELS[status] : '--' }}</text></view>
        <view v-if="local" class="detail-row"><text>原图</text><text>{{ local.original_path ? `待中转 · ${formatBytes(local.original_size)}` : '服务器已保存，本机原图已释放' }}</text></view>
        <view v-if="local" class="detail-row"><text>本机预览</text><text>{{ local.preview_path ? `${formatBytes(local.preview_size)} · ${local.preview_width}×${local.preview_height}` : '等待恢复' }}</text></view>
        <view class="detail-row"><text>永久编号</text><text class="uuid">{{ photoId }}</text></view>
      </view>
      <text class="read-only-note">小程序 V1 只查看归档信息；编辑、删除、审核和打印继续在电脑端完成。</text>
    </template>
  </view>
</template>

<style scoped>
.detail-page { padding-bottom: calc(48rpx + var(--safe-bottom)); }
.photo-preview { display: grid; place-items: center; width: 100%; height: 510rpx; overflow: hidden; border-radius: 28rpx; background: #071215; }
.photo-preview image { width: 100%; height: 100%; }
.preview-placeholder { color: var(--muted); font-size: 24rpx; }
.detail-card { overflow: hidden; margin-top: 24rpx; padding: 0 22rpx; }
.detail-row { display: grid; grid-template-columns: 150rpx 1fr; gap: 18rpx; padding: 24rpx 0; border-bottom: 1rpx solid var(--line); font-size: 24rpx; line-height: 1.5; }
.detail-row:last-child { border-bottom: 0; }
.detail-row > text:first-child { color: var(--muted); }
.detail-row > text:last-child { color: var(--text); text-align: right; word-break: break-all; }
.detail-row .status-value { color: var(--primary-strong); }
.detail-row .uuid { font-size: 21rpx; }
.read-only-note { display: block; margin: 24rpx 12rpx 0; color: var(--muted); text-align: center; font-size: 21rpx; line-height: 1.55; }
</style>
