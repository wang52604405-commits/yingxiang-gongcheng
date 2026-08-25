<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import UiIcon from '@/components/UiIcon.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import { queueRuntime } from '@/services/queue-runtime'
import { chooseCaptureSource, type CaptureSource } from '@/services/capture-entry'
import { choosePhotoPaths, getAlbumSelectionLimit } from '@/services/media-picker'
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
const albumLimit = getAlbumSelectionLimit()
const uniApi = uni

const destinationLabel = computed(() => {
  if (mode.value === 'auto') return '由系统识别后人工确认'
  const assignment = destination.value?.scope === scope.value ? destination.value.assignment : undefined
  return assignment?.unit_name || assignment?.other_node_name || '请选择工程部位'
})
const canSubmit = computed(() => Boolean(pickedPaths.value.length) && !choosing.value && !submitting.value && (mode.value === 'auto' || destination.value?.scope === scope.value))
const sourceLabel = computed(() => source.value === 'camera' ? '现场拍照' : '手机相册')
const submitLabel = computed(() => submitting.value ? '正在安全保存…' : pickedPaths.value.length ? `确认采集 ${pickedPaths.value.length} 张` : '请先选择照片')
const progressText = computed(() => {
  const progress = queueRuntime.state.prepareProgress
  return progress.total ? `${progress.current} / ${progress.total}` : ''
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
    <text class="page-subtitle">拍照和相册统一从这里进入。照片先保存在本机，确认工程信息后再同步。</text>

    <view class="media-card card">
      <view class="media-head">
        <view><text class="media-eyebrow">本次影像</text><text class="media-title">{{ pickedPaths.length ? `${pickedPaths.length} 张 · ${sourceLabel}` : sourceLabel }}</text></view>
        <button class="reselect-button pressable" :disabled="choosing || submitting" @tap="reselectMedia">{{ pickedPaths.length ? '重新选择' : '选择照片' }}</button>
      </view>
      <scroll-view v-if="pickedPaths.length" scroll-x class="preview-scroll"><view class="preview-row"><image v-for="(path, index) in pickedPaths" :key="`${path}-${index}`" class="preview-image" :src="path" mode="aspectFill" /></view></scroll-view>
      <button v-else class="empty-media pressable" :disabled="choosing" @tap="reselectMedia"><view class="empty-media-icon"><UiIcon :name="source === 'camera' ? 'camera' : 'gallery'" :size="25" /></view><text>{{ choosing ? '正在打开…' : '点击选择本次工程影像' }}</text></button>
    </view>

    <text class="field-label">影像范围</text>
    <view class="segment"><button class="segment-button pressable" :class="{ active: scope === 'engineering' }" @tap="changeScope('engineering')">工程影像</button><button class="segment-button pressable" :class="{ active: scope === 'other' }" @tap="changeScope('other')">其它影像</button></view>
    <template v-if="scope === 'engineering'">
      <text class="field-label">照片类别</text>
      <view class="segment"><button class="segment-button pressable" :class="{ active: category === 'construction' }" @tap="changeCategory('construction')">施工影像</button><button class="segment-button pressable" :class="{ active: category === 'supervision' }" @tap="changeCategory('supervision')">监理影像</button></view>
    </template>

    <view v-if="requirement" class="requirement-context">
      <view class="requirement-context-head"><text>本次按专业清单采集</text><text>{{ requirement.template_code }}</text></view>
      <text class="requirement-context-title">{{ requirement.photo_requirement_name }}</text>
      <text class="requirement-context-note">{{ requirement.timing || '对应工序施工时' }} · {{ requirement.shot_types || '按现场实际拍摄' }}<template v-if="requirement.min_photo_count"> · 至少 {{ requirement.min_photo_count }} 张</template></text>
    </view>

    <text class="field-label">归档方式</text>
    <view class="mode-grid">
      <button class="mode-card pressable" :class="{ active: mode === 'direct' }" @tap="changeMode('direct')"><view class="mode-icon"><UiIcon name="folder" :size="19" /></view><view><text class="mode-title">指定工程部位</text><text class="mode-copy">最稳妥，现场直接归档</text></view></button>
      <button class="mode-card pressable" :class="{ active: mode === 'auto' }" @tap="changeMode('auto')"><view class="mode-icon"><UiIcon name="search" :size="19" /></view><view><text class="mode-title">自动匹配</text><text class="mode-copy">上传识别后再人工确认</text></view></button>
    </view>
    <button class="destination-card pressable" :class="{ automatic: mode === 'auto' }" @tap="mode === 'direct' && chooseDestination()">
      <view class="destination-copy"><text class="destination-label">{{ mode === 'auto' ? '归档位置' : '工程部位 / 工序' }}</text><text class="destination-title">{{ destinationLabel }}</text><text v-if="mode === 'direct' && destination?.scope === scope" class="destination-code">{{ destination.assignment.unit_code || destination.assignment.other_node_code }}<template v-if="destination.assignment.process_name"> · {{ destination.assignment.process_name }}</template></text></view>
      <text v-if="mode === 'direct'" class="path-arrow">›</text><text v-else class="status-chip">识别后确认</text>
    </button>
    <view v-if="scope === 'other'" class="notice other-note"><text class="notice-dot" /><text>其它影像进入桌面端独立目录，不与施工、监理影像混放。</text></view>
    <view class="queue-status"><view class="queue-copy"><text>本机待同步空间</text><text>{{ formatBytes(queueRuntime.queueBytes.value) }} / 160MB</text></view><view class="usage-track"><view class="usage-fill" :style="{ transform: `scaleX(${queueRuntime.queueUsagePercent.value / 100})` }" /></view><text class="queue-note">现场无网也可先采集，网络恢复后自动续传。相册单次最多 {{ albumLimit }} 张。</text></view>
    <button class="primary-button pressable submit-button" :disabled="!canSubmit" @tap="submitCapture">{{ submitLabel }}</button>
    <LoadingOverlay :visible="queueRuntime.state.preparing || choosing" :message="queueRuntime.state.preparing ? (queueRuntime.state.prepareProgress.message || '正在安全保存原图') : `正在打开${sourceLabel}`" :progress="progressText" />
  </view>
</template>

<style scoped>
.capture-page{padding-bottom:calc(54rpx + var(--safe-bottom))}.media-card{margin-top:28rpx;padding:20rpx}.media-head{display:flex;align-items:center;justify-content:space-between;gap:18rpx}.media-eyebrow{display:block;color:var(--muted);font-size:20rpx}.media-title{display:block;margin-top:5rpx;color:var(--text);font-size:28rpx;font-weight:700}.reselect-button{min-height:56rpx;padding:0 18rpx;border:1rpx solid var(--line);border-radius:16rpx;color:var(--primary-strong);background:var(--surface-2);font-size:21rpx}.preview-scroll{width:100%;margin-top:18rpx;white-space:nowrap}.preview-row{display:inline-flex;gap:10rpx;padding-right:20rpx}.preview-image{flex:0 0 auto;width:146rpx;height:126rpx;border-radius:18rpx;background:var(--surface-2)}.empty-media{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12rpx;width:100%;min-height:180rpx;margin-top:18rpx;border:1rpx dashed var(--line);border-radius:20rpx;color:var(--muted);background:var(--surface-2);font-size:22rpx}.empty-media-icon{display:grid;place-items:center;width:66rpx;height:66rpx;border-radius:20rpx;color:var(--primary-strong);background:var(--primary-soft)}.mode-grid{display:grid;grid-template-columns:1fr 1fr;gap:16rpx}.mode-card{display:grid;grid-template-columns:62rpx 1fr;align-items:center;gap:12rpx;min-height:108rpx;padding:16rpx;border:1rpx solid var(--line);border-radius:22rpx;text-align:left;background:var(--surface)}.mode-card.active{border-color:var(--primary);background:var(--primary-soft)}.mode-icon{display:grid;place-items:center;width:58rpx;height:58rpx;border-radius:17rpx;color:var(--primary-strong);background:var(--primary-soft)}.mode-title{display:block;color:var(--text);font-size:24rpx;font-weight:650}.mode-copy{display:block;margin-top:5rpx;color:var(--muted);font-size:18rpx;line-height:1.35}.destination-card{display:flex;align-items:center;justify-content:space-between;width:100%;margin-top:18rpx;padding:22rpx 24rpx;border:1rpx solid var(--line);border-radius:23rpx;text-align:left;background:var(--surface)}.destination-card.automatic{background:var(--primary-soft)}.destination-copy{min-width:0}.destination-label{display:block;color:var(--muted);font-size:21rpx}.destination-title{display:block;overflow:hidden;margin-top:6rpx;color:var(--text);font-size:27rpx;font-weight:650;text-overflow:ellipsis;white-space:nowrap}.destination-code{display:block;margin-top:5rpx;color:var(--primary-strong);font-size:20rpx}.path-arrow{flex:0 0 auto;margin-left:16rpx;color:var(--muted);font-size:44rpx}.other-note{margin-top:18rpx}.queue-status{margin-top:26rpx}.queue-copy{display:flex;align-items:center;justify-content:space-between;color:var(--muted);font-size:19rpx}.usage-track{height:8rpx;margin-top:10rpx;overflow:hidden;border-radius:999rpx;background:var(--surface-2)}.usage-fill{width:100%;height:100%;transform:scaleX(0);transform-origin:left center;background:var(--primary-strong);transition:transform 180ms var(--ease-out)}.queue-note{display:block;margin-top:10rpx;color:var(--muted);font-size:18rpx;line-height:1.5}.submit-button{margin-top:26rpx}
.requirement-context{margin-top:18rpx;padding:20rpx 22rpx;border:1rpx solid rgba(38,181,167,.35);border-radius:22rpx;background:var(--primary-soft)}.requirement-context-head{display:flex;justify-content:space-between;gap:16rpx;color:var(--primary-strong);font-size:19rpx}.requirement-context-title{display:block;margin-top:8rpx;color:var(--text);font-size:26rpx;font-weight:700}.requirement-context-note{display:block;margin-top:7rpx;color:var(--muted);font-size:19rpx;line-height:1.5}
</style>
