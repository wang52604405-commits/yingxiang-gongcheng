<script setup lang="ts">
import { usePageTheme } from '@/services/theme'
const themeStyle = usePageTheme()
import { computed, ref, watch, nextTick } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import H5TabBar from '@/components/H5TabBar.vue'
import UiIcon from '@/components/UiIcon.vue'
import StablePhotoImage from '@/components/StablePhotoImage.vue'
import { queueRuntime } from '@/services/queue-runtime'
import { sessionState } from '@/services/auth'
import { bootstrapState, loadBootstrap } from '@/stores/bootstrap'
import { selectionStorage } from '@/stores/selection'
import type { CloudPhoto, ProjectSummary } from '@/types/domain'
import { shortTime } from '@/utils/format'
import { syncTabBar } from '@/services/navigation'
import { STATUS_LABELS } from '@/services/photo-state'
import { countTodayCaptures, visibleLocalHomePhotos } from '@/services/home-photo-visibility'
import { canManageProjectMembers } from '@/services/project-membership'
import { projectApplicationsApi } from '@/services/project-applications'

const fallbackProject = ref<ProjectSummary>(selectionStorage.getProject())
const project = computed(() => bootstrapState.currentProject || fallbackProject.value)
const recent = computed<CloudPhoto[]>(() => bootstrapState.recentUploads)
const loading = ref(false)
const motionReady = ref(false)
const pendingReviewCount = ref(0)
let motionPlayed = false
let reviewGeneration = 0
const localRecent = computed(() => visibleLocalHomePhotos(queueRuntime.state.photos))
const uniApi = uni

const todayCaptureCount = computed(() => countTodayCaptures(recent.value, queueRuntime.state.photos, new Date().toISOString()))
const pendingCount = computed(() => queueRuntime.pendingCount.value)
const requirementCount = computed(() => Number(project.value.requirement_count || 0))

async function loadPendingReviews(accountId: string | number, activeProject: ProjectSummary) {
  const generation = ++reviewGeneration
  pendingReviewCount.value = 0
  if (!activeProject?.id || !canManageProjectMembers(activeProject)) return
  const projectId = activeProject.id
  try {
    const rows = await projectApplicationsApi.pending(projectId)
    if (
      generation === reviewGeneration
      && String(sessionState.account?.id || '') === String(accountId)
      && String(project.value?.id || '') === String(projectId)
    ) pendingReviewCount.value = rows.length
  } catch {
    if (generation === reviewGeneration) pendingReviewCount.value = 0
  }
}

async function loadHome() {
  if (loading.value) return
  const account = sessionState.account
  if (!account) return
  loading.value = true
  try {
    await loadBootstrap(account.id, '', () => sessionState.account?.id === account.id, 30_000)
    fallbackProject.value = bootstrapState.currentProject || selectionStorage.getProject()
  } catch {
    fallbackProject.value = selectionStorage.getProject()
  } finally {
    const activeProject = bootstrapState.currentProject || fallbackProject.value
    void loadPendingReviews(account.id, activeProject)
    loading.value = false
  }
}
function prepareMotion() {
  if (motionPlayed) {
    motionReady.value = true
    return
  }
  motionPlayed = true
  motionReady.value = false
  void nextTick(() => setTimeout(() => { motionReady.value = true }, 24))
}
function openProject() { uni.navigateTo({ url: '/pages/project/select' }) }
function openApplications() {
  if (!project.value?.id || !canManageProjectMembers(project.value)) return
  uni.navigateTo({ url: '/pages/project/applications' })
}
function openRequirements() {
  if (!selectionStorage.hasProject()) {
    uni.showModal({ title: '还没有工程', content: '请先选择或加入工程。', showCancel: false, success: () => openProject() })
    return
  }
  uni.navigateTo({ url: '/pages/requirements/index' })
}
function openQueue() { uni.switchTab({ url: '/pages/queue/index' }) }

onShow(() => {
  syncTabBar(0)
  prepareMotion()
  if (sessionState.ready && sessionState.account) {
    selectionStorage.setOwner(sessionState.account.id)
    queueRuntime.setOwner(sessionState.account.id)
  }
  fallbackProject.value = selectionStorage.getProject()
  if (sessionState.ready) {
    queueRuntime.hydrate()
    void queueRuntime.resume('app-show')
    void loadHome()
  }
})
watch(() => sessionState.ready, (ready) => { if (ready && sessionState.account) void loadHome() })
</script>

<template>
  <page-meta :page-style="themeStyle" />
  <view class="page-shell home-page" :class="{ 'motion-ready': motionReady }" :style="themeStyle">
    <AppHeader
      :project-name="project.name"
      :online="queueRuntime.state.online"
      :pending-reviews="pendingReviewCount"
      @select-project="openProject"
      @open-applications="openApplications"
    />
    <view class="project-context motion-block motion-1">
      <text class="context-title">工作台</text>
    </view>
    <view class="summary-grid motion-block motion-2">
      <view class="summary-card"><text class="summary-number">{{ todayCaptureCount }}</text><text class="summary-label">今日采集</text></view>
      <button class="summary-card pressable" hover-class="summary-pressed" hover-start-time="0" hover-stay-time="60" @tap="openQueue"><text class="summary-number" :class="{ warning: pendingCount > 0 }">{{ pendingCount }}</text><text class="summary-label">待同步</text></button>
      <button class="summary-card pressable" hover-class="summary-pressed" hover-start-time="0" hover-stay-time="60" @tap="openRequirements"><text class="summary-number">{{ requirementCount || '—' }}</text><text class="summary-label">采集清单</text></button>
    </view>
    <view class="section-head motion-block motion-3"><text class="section-title">最近影像</text><button class="section-action pressable" hover-class="section-action-pressed" hover-start-time="0" hover-stay-time="55" @tap="uniApi.switchTab({ url: '/pages/library/index' })">查看全部</button></view>
    <view v-if="recent.length" class="recent-list motion-block motion-4">
      <button v-for="(photo, index) in recent" :key="photo.photo_uuid" class="recent-item pressable" hover-class="recent-item-pressed" hover-start-time="0" hover-stay-time="55" @tap="uniApi.navigateTo({ url: `/pages/photo/detail?id=${photo.photo_uuid}` })">
        <view v-if="photo.thumb_url || photo.image_url" class="recent-thumb recent-photo"><StablePhotoImage :src="photo.thumb_url || photo.image_url || ''" :identity="`${selectionStorage.getOwner()}:${project.id}:${photo.photo_uuid}`" lazy-load /></view>
        <view v-else class="recent-thumb" :class="`scene-${index % 3}`"><text>{{ photo.unit_name?.slice(-3) || photo.other_node_name?.slice(-3) || '现场' }}</text></view>
        <view class="recent-copy"><text class="recent-title">{{ photo.title }}</text><text class="recent-meta">{{ photo.unit_name || photo.other_node_name }} · {{ photo.category === 'supervision' ? '监理影像' : photo.scope === 'other' ? '其它影像' : '施工影像' }}</text></view>
        <view class="recent-state"><UiIcon class="cloud-symbol" :name="photo.status === 'desktop_imported' ? 'check' : 'upload'" :size="17" /><text>{{ shortTime(photo.created_at) }}</text></view>
      </button>
    </view>
    <view v-else-if="localRecent.length" class="recent-list motion-block motion-4">
      <button v-for="photo in localRecent" :key="photo.photo_uuid" class="recent-item pressable" hover-class="recent-item-pressed" hover-start-time="0" hover-stay-time="55" @tap="openQueue">
        <image v-if="photo.preview_path" class="recent-thumb" :src="photo.preview_path" mode="aspectFill" /><view v-else class="recent-thumb"><text>原图</text></view>
        <view class="recent-copy"><text class="recent-title">{{ photo.title }}</text><text class="recent-meta">{{ photo.draft.assignment?.unit_name || photo.draft.assignment?.other_node_name || '待匹配' }}</text></view><text class="status-chip">{{ STATUS_LABELS[photo.status] }}</text>
      </button>
    </view>
    <view v-else class="empty-state compact motion-block motion-4"><view class="empty-symbol"><UiIcon name="gallery" :size="27" /></view><text class="empty-title">还没有工程影像</text></view>
    <!-- #ifdef H5 --><H5TabBar :selected="0" :badge="queueRuntime.pendingCount.value" /><!-- #endif -->
  </view>
</template>

<style scoped>
.home-page { padding-bottom: calc(158rpx + var(--safe-bottom)); overflow-x:hidden; }
.motion-block { opacity:0; transform:translate3d(0,10rpx,0) scale(.996); }
.motion-ready .motion-block { animation:home-settle-in 240ms cubic-bezier(.215,.61,.355,1) both; }
.motion-ready .motion-1 { animation-delay:0ms; }
.motion-ready .motion-2 { animation-delay:24ms; }
.motion-ready .motion-3 { animation-delay:48ms; }
.motion-ready .motion-4 { animation-delay:72ms; }
@keyframes home-settle-in { from { opacity:0; transform:translate3d(0,10rpx,0) scale(.996); } to { opacity:1; transform:translate3d(0,0,0) scale(1); } }
.project-context { margin-top: 0; }
.context-title { display: block; color: var(--text); font-size: 40rpx; font-weight: 700; line-height: 1.25; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; margin-top: var(--space-lg); overflow: hidden; border: 1rpx solid var(--line); border-radius: 22rpx; background: var(--surface); box-shadow:0 8rpx 26rpx rgba(0,0,0,.055); }
.summary-card { display: flex; flex-direction: column; align-items: center; justify-content: center; width: 100%; min-width: 0; min-height: 106rpx; margin: 0; padding: 16rpx 12rpx; border-right: 1rpx solid var(--line); text-align: center; background: transparent; transform:translate3d(0,0,0) scale(1); transition:transform 180ms cubic-bezier(.22,1,.36,1),background 150ms cubic-bezier(.215,.61,.355,1),opacity 120ms ease; }
.summary-card:last-child { border-right: 0; }
.summary-card.summary-pressed { transform:translate3d(0,1rpx,0) scale(.985); background:var(--primary-soft); opacity:.96; }
.summary-number { color: var(--text); font-size: 34rpx; font-weight: 700; line-height: 1.15; transform:scale(1); transition:transform 180ms cubic-bezier(.22,1,.36,1); }
.summary-card.summary-pressed .summary-number { transform:scale(.975); }
.summary-number.warning { color: var(--warning); }
.summary-label { margin-top: 6rpx; color: var(--muted); font-size: 22rpx; line-height: 1.2; }
.section-action { transition:transform 160ms cubic-bezier(.22,1,.36,1),opacity 120ms ease; }
.section-action.section-action-pressed { transform:scale(.97); opacity:.72; }
.recent-list { display: grid; gap: 0; overflow: hidden; border: 1rpx solid var(--line); border-radius: 22rpx; background: var(--surface); box-shadow:0 8rpx 28rpx rgba(0,0,0,.045); }
.recent-item { display: grid; grid-template-columns: 108rpx 1fr auto; align-items: center; gap: 18rpx; width: 100%; min-height: 112rpx; padding: 12rpx 16rpx; border-bottom: 1rpx solid var(--line); text-align: left; background: transparent; transform:translate3d(0,0,0) scale(1); transition:transform 180ms cubic-bezier(.22,1,.36,1),background 150ms cubic-bezier(.215,.61,.355,1),opacity 120ms ease; }
.recent-item.recent-item-pressed { transform:scale(.993); background:var(--primary-soft); opacity:.96; }
.recent-item:last-child { border-bottom: 0; }
.recent-thumb { width: 108rpx; height: 86rpx; overflow: hidden; border-radius: 17rpx; background: #9fcfd8; transform:scale(1); transition:transform 220ms cubic-bezier(.22,1,.36,1); }
.recent-item.recent-item-pressed .recent-thumb { transform:scale(1.025); }
view.recent-thumb:not(.recent-photo) { display: flex; align-items: flex-end; padding: 8rpx; color: #09262a; background: linear-gradient(155deg, #9cd7e3 0 38%, #d6c69e 39% 60%, #668876 61%); font-size: 20rpx; font-weight: 700; }
view.recent-thumb.scene-1 { background: linear-gradient(105deg, #86ccde 0 44%, #b5b9b4 45% 67%, #517c6d 68%); }
view.recent-thumb.scene-2 { background: linear-gradient(160deg, #9bdbe8 0 34%, #c5b98d 35% 61%, #6e8f69 62%); }
.recent-copy { min-width: 0; }
.recent-title { display: block; overflow: hidden; color: var(--text); font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.recent-meta { display: block; overflow: hidden; margin-top: 8rpx; color: var(--muted); font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
.recent-state { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4rpx; color: var(--primary-strong); font-size: 20rpx; transform:scale(1); transition:transform 180ms cubic-bezier(.22,1,.36,1),opacity 120ms ease; }
.recent-item.recent-item-pressed .recent-state { transform:scale(.96); opacity:.82; }
.cloud-symbol { font-size: 29rpx; }
.empty-state.compact { min-height: 280rpx; }
@media (prefers-reduced-motion: reduce) {
  .motion-block { opacity:1; transform:none; }
  .motion-ready .motion-block { animation:none; }
  .summary-card,.summary-number,.recent-item,.recent-thumb,.recent-state,.section-action { transition:none; }
}
</style>
