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
    <PageHeader title="确认归档位置" />

    <view v-if="processing" class="processing-bar"><view class="processing-status"><text class="notice-dot" /><text>上传识别中</text></view><button class="refresh-button pressable" @tap="refresh">刷新</button></view>

    <view v-if="photos.length" class="review-list">
      <view v-for="photo in photos" :key="photo.photo_uuid" class="review-card card">
        <image v-if="photo.preview_path" class="review-thumb" :src="photo.preview_path" mode="aspectFill" />
        <view v-else class="review-thumb preview-waiting">预览处理中</view>
        <view class="review-copy">
          <view class="review-head"><input v-model="photo.title" class="review-title" placeholder="照片题名" /><text v-if="photo.match_candidates?.[0]" class="confidence" :class="{ high: photo.match_candidates[0].confidence >= 0.85 }">{{ Math.round(photo.match_candidates[0].confidence * 100) }}%</text></view>
          <text class="review-location">{{ selections[photo.photo_uuid]?.unit_name || selections[photo.photo_uuid]?.other_node_name || '识别中…' }}<template v-if="selections[photo.photo_uuid]?.process_name"> · {{ selections[photo.photo_uuid].process_name }}</template></text>
          <text v-if="selections[photo.photo_uuid]?.unit_code || selections[photo.photo_uuid]?.other_node_code" class="review-code">{{ selections[photo.photo_uuid]?.unit_code || selections[photo.photo_uuid]?.other_node_code }}</text>
        </view>
      </view>
    </view>

    <view v-if="photos.length" class="confirm-actions"><button class="secondary-button pressable" @tap="chooseManual">更改位置</button><button class="primary-button pressable" :disabled="!readyToConfirm || submitting" @tap="confirm">{{ submitting ? '提交中…' : '确认归档' }}</button></view>

    <LoadingOverlay :visible="submitting" message="正在保存归档信息" />
  </view>
</template>

<style scoped>
.confirm-page { padding-bottom: calc(48rpx + var(--safe-bottom)); }
.processing-bar { display:flex; align-items:center; justify-content:space-between; min-height:72rpx; margin-bottom:20rpx; padding:0 18rpx; border-radius:18rpx; color:var(--muted); background:var(--surface); font-size:23rpx; }
.processing-status { display:flex; align-items:center; gap:16rpx; }
.processing-status .notice-dot { margin-top:0; }
.review-list { display: grid; gap: 18rpx; margin: 0 0 24rpx; }
.review-card { display: grid; grid-template-columns: 112rpx minmax(0, 1fr); align-items: start; gap: 16rpx; padding: 18rpx; }
.review-thumb { width: 112rpx; height: 104rpx; border-radius: 18rpx; background: var(--surface-2); }
.preview-waiting { display: grid; place-items: center; color: var(--muted); font-size: 20rpx; }
.review-copy { min-width: 0; }
.review-head { display: flex; align-items: center; min-width: 0; gap: 12rpx; }
.review-title { flex: 1; min-width: 0; height: 44rpx; color: var(--text); font-size: 26rpx; font-weight: 600; }
.review-location { display: block; overflow: hidden; margin-top: 8rpx; color: var(--muted); font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
.review-code { display: block; margin-top: 6rpx; color: var(--primary-strong); font-size: 22rpx; }
.confidence { flex: 0 0 auto; padding: 8rpx 12rpx; border-radius: 999rpx; color: var(--warning); background: rgba(241, 179, 75, 0.13); font-size: 21rpx; }
.confidence.high { color: var(--primary-strong); background: var(--primary-soft); }
.confirm-actions { display:grid; grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr); gap:12rpx; margin-top:24rpx; }
.confirm-actions .primary-button, .confirm-actions .secondary-button { min-height:84rpx; padding:14rpx 16rpx; font-size:26rpx; }
.refresh-button { display:flex; align-items:center; justify-content:center; min-height:40px; padding:0 12rpx; color:var(--primary-strong); background:transparent; font-size:23rpx; }
</style>
