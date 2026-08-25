<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import { queueRuntime } from '@/services/queue-runtime'
import { selectionStorage } from '@/stores/selection'
import type { Assignment } from '@/types/domain'

const clientBatchId = ref('')
const submitting = ref(false)
const selections = reactive<Record<string, Assignment>>({})
const batch = computed(() => queueRuntime.state.batches.find((item) => item.client_batch_id === clientBatchId.value))
const photos = computed(() => queueRuntime.state.photos.filter((photo) => photo.client_batch_id === clientBatchId.value))
const readyToConfirm = computed(() => photos.value.length > 0 && photos.value.every((photo) => photo.status === 'needs_review' && Boolean(selections[photo.photo_uuid]?.unit_code || selections[photo.photo_uuid]?.other_node_code)))
const processing = computed(() => photos.value.some((photo) => ['local_ready', 'uploading', 'server_saved', 'analyzing'].includes(photo.status)))

watch(photos, (items) => {
  const manual = selectionStorage.getDestination()
  items.forEach((photo) => {
    if (selections[photo.photo_uuid]) return
    const candidate = photo.match_candidates?.[0]
    if (candidate) {
      selections[photo.photo_uuid] = {
        unit_code: candidate.unit_code,
        unit_name: candidate.unit_name,
        process_name: candidate.process_name,
        other_node_code: candidate.other_node_code,
        other_node_name: candidate.other_node_name,
      }
    } else if (manual?.scope === photo.draft.scope) {
      selections[photo.photo_uuid] = { ...manual.assignment }
    }
  })
}, { immediate: true, deep: true })

function chooseManual() {
  uni.navigateTo({ url: `/pages/destination/select?scope=${batch.value?.draft.scope || 'engineering'}&return=confirm` })
}

function applyManualSelection() {
  const manual = selectionStorage.getDestination()
  if (!manual || manual.scope !== batch.value?.draft.scope) return
  photos.value.forEach((photo) => { selections[photo.photo_uuid] = { ...manual.assignment } })
}

async function refresh() {
  await queueRuntime.resume('manual')
  if (photos.value.some((photo) => photo.status === 'failed')) uni.showToast({ title: '部分照片处理失败，请到队列重试', icon: 'none' })
}

async function confirm() {
  if (!readyToConfirm.value) {
    uni.showToast({ title: '请先确认所有照片的归档位置', icon: 'none' })
    return
  }
  submitting.value = true
  try {
    await queueRuntime.confirmBatch(clientBatchId.value, photos.value.map((photo) => ({
      photo_uuid: photo.photo_uuid,
      assignment: selections[photo.photo_uuid],
      title: photo.title,
      photo_date: photo.photo_date,
    })))
    uni.showToast({ title: '已提交电脑端归档', icon: 'success' })
    setTimeout(() => uni.switchTab({ url: '/pages/queue/index' }), 450)
  } catch (error) {
    uni.showModal({ title: '确认失败', content: error instanceof Error ? error.message : '请稍后重试', showCancel: false })
  } finally {
    submitting.value = false
  }
}

onLoad((query) => {
  clientBatchId.value = String(query?.batch || '')
  queueRuntime.hydrate()
  void refresh()
})
onShow(applyManualSelection)
</script>

<template>
  <view class="page-shell no-tabs confirm-page">
    <PageHeader title="确认自动匹配" :subtitle="photos.length ? `${photos.length} 张照片` : '读取上传批次'" />

    <view v-if="processing" class="notice processing-note"><text class="notice-dot" /><view><text class="notice-title">正在上传并识别</text><text>请保持小程序在前台。退出微信后不会继续后台上传，重新进入可续传。</text></view></view>
    <view v-else-if="photos.some(photo => photo.status === 'needs_review')" class="notice"><text class="notice-dot" /><view><text class="notice-title">识别结果已返回</text><text>高置信结果也请在提交前看一眼，避免归错单元。</text></view></view>

    <view v-if="photos.length" class="review-list">
      <view v-for="photo in photos" :key="photo.photo_uuid" class="review-card card">
        <image v-if="photo.preview_path" class="review-thumb" :src="photo.preview_path" mode="aspectFill" />
        <view v-else class="review-thumb preview-waiting">预览处理中</view>
        <view class="review-copy">
          <input v-model="photo.title" class="review-title" placeholder="照片题名" />
          <text class="review-location">{{ selections[photo.photo_uuid]?.unit_name || selections[photo.photo_uuid]?.other_node_name || '等待识别结果' }}<template v-if="selections[photo.photo_uuid]?.process_name"> · {{ selections[photo.photo_uuid].process_name }}</template></text>
          <text class="review-code">{{ selections[photo.photo_uuid]?.unit_code || selections[photo.photo_uuid]?.other_node_code || photo.status }}</text>
        </view>
        <text v-if="photo.match_candidates?.[0]" class="confidence" :class="{ high: photo.match_candidates[0].confidence >= 0.85 }">{{ Math.round(photo.match_candidates[0].confidence * 100) }}%</text>
      </view>
    </view>

    <button v-if="photos.length" class="secondary-button pressable manual-button" @tap="chooseManual">人工选择归档位置</button>
    <button class="primary-button pressable" :disabled="!readyToConfirm || submitting" @tap="confirm">{{ submitting ? '正在提交…' : '确认并交给电脑端归档' }}</button>
    <button v-if="processing" class="refresh-button pressable" @tap="refresh">刷新识别状态</button>

    <LoadingOverlay :visible="submitting" message="正在保存归档信息" />
  </view>
</template>

<style scoped>
.confirm-page { padding-bottom: calc(48rpx + var(--safe-bottom)); }
.processing-note { margin-bottom: 22rpx; }
.notice-title { display: block; margin-bottom: 5rpx; color: var(--text); font-weight: 650; }
.review-list { display: grid; gap: 16rpx; margin: 22rpx 0; }
.review-card { display: grid; grid-template-columns: 126rpx 1fr auto; align-items: center; gap: 16rpx; padding: 14rpx; }
.review-thumb { width: 126rpx; height: 108rpx; border-radius: 19rpx; background: var(--surface-2); }
.preview-waiting { display: grid; place-items: center; color: var(--muted); font-size: 18rpx; }
.review-copy { min-width: 0; }
.review-title { width: 100%; height: 44rpx; color: var(--text); font-size: 26rpx; font-weight: 650; }
.review-location { display: block; overflow: hidden; margin-top: 7rpx; color: var(--muted); font-size: 21rpx; text-overflow: ellipsis; white-space: nowrap; }
.review-code { display: block; margin-top: 5rpx; color: var(--primary-strong); font-size: 19rpx; }
.confidence { align-self: start; padding: 8rpx 12rpx; border-radius: 999rpx; color: var(--warning); background: rgba(241, 179, 75, 0.13); font-size: 19rpx; }
.confidence.high { color: var(--primary-strong); background: var(--primary-soft); }
.manual-button { margin: 24rpx 0 16rpx; }
.refresh-button { width: 100%; min-height: 70rpx; margin-top: 16rpx; color: var(--primary-strong); font-size: 24rpx; }
</style>
