<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import UiIcon from '@/components/UiIcon.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import { queueRuntime } from '@/services/queue-runtime'
import { chooseCaptureSource, type CaptureSource } from '@/services/capture-entry'
import { choosePhotoPaths } from '@/services/media-picker'
import { selectionStorage } from '@/stores/selection'
import type { CaptureRequirementRef, PhotoCategory, Scope, UploadDraft, UploadMode } from '@/types/domain'
import { formatBytes } from '@/utils/format'

const project = ref(selectionStorage.getProject())
const scope = ref<Scope>('engineering')
const category = ref<PhotoCategory>('construction')
const mode = ref<UploadMode>('direct')
const requirement = ref<CaptureRequirementRef | null>(null)
const destination = ref(selectionStorage.getDestination())
const source = ref<CaptureSource>('camera')
const pickedPaths = ref<string[]>([])
const choosing = ref(false)
const submitting = ref(false)
const sourceInitialized = ref(false)
const uniApi = uni

const destinationLabel = computed(() => {
  const assignment = destination.value?.scope === scope.value ? destination.value.assignment : undefined
  return assignment?.unit_name || assignment?.other_node_name || (scope.value === 'engineering' ? '选择工程部位' : '选择其它影像目录')
})
const canSubmit = computed(() => Boolean(pickedPaths.value.length) && !choosing.value && !submitting.value && (mode.value === 'auto' || destination.value?.scope === scope.value))
const sourceLabel = computed(() => source.value === 'camera' ? '现场拍照' : '手机相册')
const submitLabel = computed(() => submitting.value ? '正在保存…' : pickedPaths.value.length ? `确认采集 ${pickedPaths.value.length} 张` : '请先选择照片')
const progressText = computed(() => {
  const progress = queueRuntime.state.prepareProgress
  return progress.total ? `${progress.current} / ${progress.total}` : ''
})
const requirementNote = computed(() => {
  const item = requirement.value
  if (!item) return ''
  return [item.timing, item.shot_types, item.min_photo_count ? `至少 ${item.min_photo_count} 张` : ''].filter(Boolean).join(' · ')
})

function applyStoredState() {
  project.value = selectionStorage.getProject()
  destination.value = selectionStorage.getDestination()
  const preset = selectionStorage.getUploadPreset()
  scope.value = preset.scope || scope.value
  category.value = preset.category || category.value
  mode.value = preset.mode || mode.value
  requirement.value = preset.requirement?.template_code ? preset.requirement : null
  if (scope.value !== 'engineering' || category.value !== 'construction') requirement.value = null
}
function savePreset() {
  selectionStorage.setUploadPreset({
    scope: scope.value,
    category: category.value,
    mode: mode.value,
    requirement: requirement.value || undefined,
  })
}
function chooseDestination() { uni.navigateTo({ url: `/pages/destination/select?scope=${scope.value}&return=capture` }) }

async function pickMedia(nextSource: CaptureSource = source.value) {
  if (queueRuntime.queueUsagePercent.value >= 100) {
    uni.showModal({ title: '本机同步队列已满', content: '待同步影像已经达到 160MB，请联网完成同步后再继续采集。', showCancel: false })
    return
  }
  source.value = nextSource
  choosing.value = true
  try {
    const paths = await choosePhotoPaths(nextSource)
    if (paths.length) pickedPaths.value = paths
  } catch (error: any) {
    if (!String(error?.errMsg || '').includes('cancel')) uni.showModal({ title: '照片选择失败', content: error instanceof Error ? error.message : '请稍后重试', showCancel: false })
  } finally {
    choosing.value = false
  }
}
async function reselectMedia() {
  const nextSource = await chooseCaptureSource()
  if (nextSource) await pickMedia(nextSource)
}
async function submitCapture() {
  if (!project.value.id) {
    uni.showModal({ title: '尚未同步工程', content: '请先在原电脑登录同一账号并同步工程。', showCancel: false })
    return
  }
  if (!pickedPaths.value.length) { await reselectMedia(); return }
  if (mode.value === 'direct' && destination.value?.scope !== scope.value) {
    uni.showToast({ title: '请先选择工程部位', icon: 'none' })
    return
  }
  submitting.value = true
  try {
    const draft: UploadDraft = {
      project_id: project.value.id,
      scope: scope.value,
      category: scope.value === 'engineering' ? category.value : undefined,
      mode: mode.value,
      assignment: mode.value === 'direct' ? destination.value?.assignment : undefined,
      requirement: scope.value === 'engineering' && category.value === 'construction'
        ? requirement.value || undefined
        : undefined,
    }
    const batch = await queueRuntime.enqueue([...pickedPaths.value], draft)
    pickedPaths.value = []
    if (mode.value === 'auto') {
      uni.navigateTo({ url: `/pages/upload/confirm?batch=${batch.client_batch_id}` })
      return
    }
    uni.showToast({ title: '已加入同步队列', icon: 'success' })
    setTimeout(() => uni.switchTab({ url: '/pages/home/index' }), 450)
  } catch (error) {
    uni.showModal({ title: '影像未加入队列', content: error instanceof Error ? error.message : '处理照片失败', showCancel: false })
  } finally {
    submitting.value = false
  }
}
function changeScope(next: Scope) {
  if (scope.value === next) return
  scope.value = next
  if (destination.value?.scope !== next) destination.value = null
  if (next !== 'engineering') requirement.value = null
  savePreset()
}
function changeMode(next: UploadMode) {
  mode.value = next
  savePreset()
}
function changeCategory(next: PhotoCategory) {
  category.value = next
  if (next !== 'construction') requirement.value = null
  savePreset()
}

onLoad((query) => {
  applyStoredState()
  source.value = query?.source === 'album' ? 'album' : 'camera'
  if (query?.autopick === '1' && !sourceInitialized.value) {
    sourceInitialized.value = true
    setTimeout(() => { void pickMedia(source.value) }, 80)
  }
})
onShow(() => {
  project.value = selectionStorage.getProject()
  applyStoredState()
})
</script>

<template>
  <view class="page-shell no-tabs capture-page">
    <AppHeader :project-name="project.name" :online="queueRuntime.state.online" @select-project="uniApi.navigateTo({ url: '/pages/project/select' })" />
    <text class="page-title">采集影像</text>

    <view class="media-card card">
      <view class="media-head">
        <text class="media-title">{{ pickedPaths.length ? `${pickedPaths.length} 张影像` : '选择影像' }}</text>
        <button v-if="pickedPaths.length" class="reselect-button pressable" :disabled="choosing || submitting" @tap="reselectMedia">更换</button>
      </view>
      <scroll-view v-if="pickedPaths.length" scroll-x class="preview-scroll"><view class="preview-row"><image v-for="(path, index) in pickedPaths" :key="`${path}-${index}`" class="preview-image" :src="path" mode="aspectFill" /></view></scroll-view>
      <button v-else class="empty-media pressable" :disabled="choosing" @tap="reselectMedia"><view class="empty-media-icon"><UiIcon :name="source === 'camera' ? 'camera' : 'gallery'" :size="25" /></view><text>{{ choosing ? '正在打开…' : source === 'camera' ? '开始拍照' : '从相册选择' }}</text></button>
    </view>

    <view class="capture-settings card">
      <view class="settings-group">
        <text class="field-label">影像范围</text>
        <view class="segment"><button class="segment-button pressable" :class="{ active: scope === 'engineering' }" @tap="changeScope('engineering')">工程影像</button><button class="segment-button pressable" :class="{ active: scope === 'other' }" @tap="changeScope('other')">其它影像</button></view>
      </view>
      <view v-if="scope === 'engineering'" class="settings-group">
        <text class="field-label">照片类别</text>
        <view class="segment"><button class="segment-button pressable" :class="{ active: category === 'construction' }" @tap="changeCategory('construction')">施工影像</button><button class="segment-button pressable" :class="{ active: category === 'supervision' }" @tap="changeCategory('supervision')">监理影像</button></view>
      </view>

      <view v-if="requirement" class="requirement-context">
        <text class="requirement-context-kicker">专业清单</text>
        <text class="requirement-context-title">{{ requirement.photo_requirement_name }}</text>
        <text v-if="requirementNote" class="requirement-context-note">{{ requirementNote }}</text>
      </view>

      <view class="settings-group">
        <text class="field-label">归档方式</text>
        <view class="segment mode-segment">
          <button class="segment-button pressable" :class="{ active: mode === 'direct' }" @tap="changeMode('direct')">指定部位</button>
          <button class="segment-button pressable" :class="{ active: mode === 'auto' }" @tap="changeMode('auto')">自动匹配</button>
        </view>
      </view>
      <button v-if="mode === 'direct'" class="destination-card pressable" @tap="chooseDestination">
        <view class="destination-copy"><text class="destination-title">{{ destinationLabel }}</text><text v-if="destination?.scope === scope" class="destination-code">{{ destination.assignment.unit_code || destination.assignment.other_node_code }}<template v-if="destination.assignment.process_name"> · {{ destination.assignment.process_name }}</template></text></view>
        <view class="path-arrow"><UiIcon name="chevron" :size="18" /></view>
      </button>
      <view v-else class="destination-card automatic"><text class="destination-title">上传后自动匹配</text><text class="status-chip">需确认</text></view>
    </view>
    <view v-if="queueRuntime.queueBytes.value > 0" class="queue-status"><view class="queue-copy"><text>本机待上传</text><text>{{ formatBytes(queueRuntime.queueBytes.value) }} / 160MB</text></view><view class="usage-track"><view class="usage-fill" :style="{ transform: `scaleX(${queueRuntime.queueUsagePercent.value / 100})` }" /></view></view>
    <button class="primary-button pressable submit-button" :disabled="!canSubmit" @tap="submitCapture">{{ submitLabel }}</button>
    <LoadingOverlay :visible="queueRuntime.state.preparing || choosing" :message="queueRuntime.state.preparing ? (queueRuntime.state.prepareProgress.message || '正在保存原图') : `正在打开${sourceLabel}`" :progress="progressText" />
  </view>
</template>

<style scoped>
.capture-page { padding-bottom: calc(54rpx + var(--safe-bottom)); }
.media-card { margin-top: 24rpx; padding: 24rpx; }
.media-head { display: flex; align-items: center; justify-content: space-between; gap: 18rpx; }
.media-title { display: block; color: var(--text); font-size: 28rpx; font-weight: 700; }
.reselect-button { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; padding: 0 20rpx; border: 1rpx solid var(--line); border-radius: 16rpx; color: var(--primary-strong); background: var(--surface-2); font-size: 22rpx; line-height: 1.25; text-align: center; }
.preview-scroll { width: 100%; margin-top: 18rpx; white-space: nowrap; }
.preview-row { display: inline-flex; gap: 10rpx; padding-right: 20rpx; }
.preview-image { flex: 0 0 auto; width: 146rpx; height: 126rpx; border-radius: 18rpx; background: var(--surface-2); }
.empty-media { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12rpx; width: 100%; min-height: 180rpx; margin-top: 18rpx; border: 1rpx solid rgba(45, 185, 170, 0.34); border-radius: 20rpx; color: var(--primary-strong); background: var(--primary-soft); font-size: 23rpx; font-weight: 600; }
.empty-media-icon { display: grid; place-items: center; width: 66rpx; height: 66rpx; border-radius: 20rpx; color: var(--primary-strong); background: var(--primary-soft); }
.capture-settings { margin-top: 24rpx; padding: 22rpx; }
.capture-settings > .settings-group:not(:first-child) { margin-top: 24rpx; padding-top: 24rpx; border-top: 1rpx solid var(--line); }
.capture-settings .field-label { margin: 0 0 12rpx; }
.destination-card { display: flex; align-items: center; justify-content: space-between; width: 100%; margin-top: 16rpx; padding: 19rpx 20rpx; border: 1rpx solid var(--line); border-radius: 18rpx; text-align: left; background: var(--surface-2); }
.destination-card.automatic { background: var(--primary-soft); }
.destination-copy { min-width: 0; }
.destination-title { display: block; overflow: hidden; color: var(--text); font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.destination-code { display: block; margin-top: 5rpx; color: var(--primary-strong); font-size: 20rpx; }
.path-arrow { display: grid; flex: 0 0 auto; place-items: center; width: 36rpx; height: 52rpx; margin-left: 16rpx; color: var(--muted); }
.queue-status { margin-top: 26rpx; }
.queue-copy { display: flex; align-items: center; justify-content: space-between; color: var(--muted); font-size: 21rpx; }
.usage-track { height: 8rpx; margin-top: 10rpx; overflow: hidden; border-radius: 999rpx; background: var(--surface-2); }
.usage-fill { width: 100%; height: 100%; transform: scaleX(0); transform-origin: left center; background: var(--primary-strong); transition: transform 180ms var(--ease-out); }
.submit-button { margin-top: 26rpx; }
.requirement-context { margin-top: 22rpx; padding: 18rpx 20rpx; border: 1rpx solid rgba(38, 181, 167, 0.35); border-radius: 18rpx; background: var(--primary-soft); }
.requirement-context-kicker { display:block; color:var(--primary-strong); font-size:22rpx; }
.requirement-context-title { display: block; margin-top: 8rpx; color: var(--text); font-size: 26rpx; font-weight: 700; }
.requirement-context-note { display: block; margin-top: 7rpx; color: var(--muted); font-size: 22rpx; line-height: 1.5; }
</style>
