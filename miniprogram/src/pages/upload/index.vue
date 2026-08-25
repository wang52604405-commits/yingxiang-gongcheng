<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import H5TabBar from '@/components/H5TabBar.vue'
import UiIcon from '@/components/UiIcon.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import { queueRuntime } from '@/services/queue-runtime'
import { syncTabBar } from '@/services/navigation'
import { choosePhotoPaths, getAlbumSelectionLimit } from '@/services/media-picker'
import { selectionStorage } from '@/stores/selection'
import type { PhotoCategory, Scope, UploadDraft, UploadMode } from '@/types/domain'
import { formatBytes } from '@/utils/format'

const project = ref(selectionStorage.getProject())
const scope = ref<Scope>('engineering')
const category = ref<PhotoCategory>('construction')
const mode = ref<UploadMode>('direct')
const destination = ref(selectionStorage.getDestination())
const choosing = ref(false)
const albumLimit = getAlbumSelectionLimit()
const uniApi = uni
const destinationLabel = computed(() => {
  if (mode.value === 'auto') return '自动识别单元与工序'
  const assignment = destination.value?.scope === scope.value ? destination.value.assignment : undefined
  return assignment?.unit_name || assignment?.other_node_name || '请选择归档位置'
})
const canChoose = computed(() => mode.value === 'auto' || destination.value?.scope === scope.value)
const progressText = computed(() => {
  const progress = queueRuntime.state.prepareProgress
  return progress.total ? `${progress.current} / ${progress.total}` : ''
})

function chooseDestination() {
  uni.navigateTo({ url: `/pages/destination/select?scope=${scope.value}&return=upload` })
}

async function pick(source: 'camera' | 'album') {
  if (!canChoose.value) {
    uni.showToast({ title: '请先选择归档位置', icon: 'none' })
    return
  }
  if (queueRuntime.queueUsagePercent.value >= 100) {
    uni.showModal({ title: '本机队列已满', content: '待传影像已经达到 160MB，请联网完成上传后再继续拍摄。', showCancel: false })
    return
  }
  choosing.value = true
  try {
    const paths = await choosePhotoPaths(source)
    if (!paths.length) return
    const draft: UploadDraft = {
      project_id: project.value.id,
      scope: scope.value,
      category: scope.value === 'engineering' ? category.value : undefined,
      mode: mode.value,
      assignment: mode.value === 'direct' ? destination.value?.assignment : undefined,
    }
    const batch = await queueRuntime.enqueue(paths, draft)
    if (mode.value === 'auto') {
      uni.navigateTo({ url: `/pages/upload/confirm?batch=${batch.client_batch_id}` })
    } else {
      uni.showToast({ title: `${paths.length} 张已安全加入队列`, icon: 'none' })
      setTimeout(() => uni.switchTab({ url: '/pages/queue/index' }), 500)
    }
  } catch (error: any) {
    if (!String(error?.errMsg || '').includes('cancel')) uni.showModal({ title: '照片未加入队列', content: error instanceof Error ? error.message : '处理照片失败', showCancel: false })
  } finally {
    choosing.value = false
  }
}

onShow(() => {
  syncTabBar(2)
  project.value = selectionStorage.getProject()
  destination.value = selectionStorage.getDestination()
  const preset = selectionStorage.getUploadPreset()
  scope.value = preset.scope || scope.value
  category.value = preset.category || category.value
  mode.value = preset.mode || mode.value
})
</script>

<template>
  <view class="page-shell">
    <AppHeader :project-name="project.name" :online="queueRuntime.state.online" @select-project="uniApi.navigateTo({ url: '/pages/project/select' })" />
    <text class="page-title">上传影像</text>
    <text class="page-subtitle">照片先安全保存在本机，再按电脑端规则归档。</text>

    <text class="field-label">归档范围</text>
    <view class="segment">
      <button class="segment-button pressable" :class="{ active: scope === 'engineering' }" @tap="scope = 'engineering'">工程影像</button>
      <button class="segment-button pressable" :class="{ active: scope === 'other' }" @tap="scope = 'other'">其它影像</button>
    </view>

    <template v-if="scope === 'engineering'">
      <text class="field-label">照片类别</text>
      <view class="segment">
        <button class="segment-button pressable" :class="{ active: category === 'construction' }" @tap="category = 'construction'">施工影像</button>
        <button class="segment-button pressable" :class="{ active: category === 'supervision' }" @tap="category = 'supervision'">监理影像</button>
      </view>
    </template>

    <text class="field-label">归档方式</text>
    <view class="mode-grid">
      <button class="mode-card pressable" :class="{ active: mode === 'direct' }" @tap="mode = 'direct'">
        <view class="mode-icon"><UiIcon name="folder" :size="19" /></view>
        <view><text class="mode-title">指定位置</text><text class="mode-copy">拍摄前选择单元</text></view>
      </button>
      <button class="mode-card pressable" :class="{ active: mode === 'auto' }" @tap="mode = 'auto'">
        <view class="mode-icon"><UiIcon name="search" :size="19" /></view>
        <view><text class="mode-title">自动匹配</text><text class="mode-copy">上传后识别确认</text></view>
      </button>
    </view>

    <button class="destination-card pressable" :class="{ automatic: mode === 'auto' }" @tap="mode === 'direct' && chooseDestination()">
      <view>
        <text class="destination-label">{{ mode === 'auto' ? '识别方式' : '归档位置' }}</text>
        <text class="destination-title">{{ destinationLabel }}</text>
        <text v-if="mode === 'direct' && destination?.scope === scope" class="destination-code">{{ destination.assignment.unit_code || destination.assignment.other_node_code }}<template v-if="destination.assignment.process_name"> · {{ destination.assignment.process_name }}</template></text>
      </view>
      <text v-if="mode === 'direct'" class="path-arrow">›</text>
      <text v-else class="status-chip">上传后确认</text>
    </button>

    <view v-if="scope === 'other'" class="notice other-note">
      <text class="notice-dot" />
      <text>其它影像使用电脑端独立目录树，不会混入施工或监理分类。</text>
    </view>

    <view class="source-grid">
      <button class="source-button camera pressable" :disabled="choosing" @tap="pick('camera')">
        <UiIcon class="source-icon" name="camera" :size="21" /><view><text class="source-title">现场拍摄</text><text class="source-copy">调用后置相机</text></view>
      </button>
      <button class="source-button album pressable" :disabled="choosing" @tap="pick('album')">
        <UiIcon class="source-icon" name="gallery" :size="21" /><view><text class="source-title">从相册选择</text><text class="source-copy">一次最多 {{ albumLimit }} 张</text></view>
      </button>
    </view>

    <view class="limit-row">
      <text>原图安全中转 · 预览 ≤100KB</text>
      <text>本机影像 {{ formatBytes(queueRuntime.queueBytes.value) }} / 160MB</text>
    </view>
    <view class="usage-track"><view class="usage-fill" :style="{ transform: `scaleX(${queueRuntime.queueUsagePercent.value / 100})` }" /></view>

    <LoadingOverlay :visible="queueRuntime.state.preparing" :message="queueRuntime.state.prepareProgress.message || '正在安全保存原图'" :progress="progressText" />
    <!-- #ifdef H5 -->
    <H5TabBar :selected="2" :badge="queueRuntime.pendingCount.value" />
    <!-- #endif -->
  </view>
</template>

<style scoped>
.mode-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16rpx; }
.mode-card { display: grid; grid-template-columns: 66rpx 1fr; align-items: center; gap: 14rpx; min-height: 104rpx; padding: 16rpx; border: 1rpx solid var(--line); border-radius: 22rpx; text-align: left; background: var(--surface); }
.mode-card.active { border-color: var(--primary); background: var(--primary-soft); }
.mode-icon { display: grid; place-items: center; width: 62rpx; height: 62rpx; border-radius: 18rpx; color: var(--primary-strong); background: var(--primary-soft); font-size: 30rpx; }
.mode-title { display: block; color: var(--text); font-size: 25rpx; font-weight: 650; }
.mode-copy { display: block; margin-top: 6rpx; color: var(--muted); font-size: 20rpx; }
.destination-card { display: flex; align-items: center; justify-content: space-between; width: 100%; margin-top: 18rpx; padding: 22rpx 24rpx; border: 1rpx solid var(--line); border-radius: 23rpx; text-align: left; background: var(--surface); }
.destination-card.automatic { background: var(--primary-soft); }
.destination-label { display: block; color: var(--muted); font-size: 21rpx; }
.destination-title { display: block; margin-top: 6rpx; color: var(--text); font-size: 27rpx; font-weight: 650; }
.destination-code { display: block; margin-top: 5rpx; color: var(--primary-strong); font-size: 20rpx; }
.path-arrow { color: var(--muted); font-size: 44rpx; }
.other-note { margin-top: 18rpx; }
.source-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16rpx; margin-top: 26rpx; }
.source-button { display: flex; align-items: center; gap: 14rpx; min-height: 108rpx; padding: 18rpx; border-radius: 23rpx; color: #041a1a; text-align: left; background: var(--primary-strong); }
.source-button.album { color: var(--text); background: var(--surface-2); }
.source-icon { font-size: 34rpx; }
.source-title { display: block; font-size: 26rpx; font-weight: 700; }
.source-copy { display: block; margin-top: 5rpx; font-size: 20rpx; opacity: 0.72; }
.limit-row { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; margin-top: 28rpx; color: var(--muted); font-size: 19rpx; }
.usage-track { height: 8rpx; margin-top: 10rpx; overflow: hidden; border-radius: 999rpx; background: var(--surface-2); }
.usage-fill { width: 100%; height: 100%; transform: scaleX(0); transform-origin: left center; background: var(--primary-strong); transition: transform 180ms var(--ease-out); }
</style>
