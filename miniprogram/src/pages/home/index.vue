<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import H5TabBar from '@/components/H5TabBar.vue'
import UiIcon from '@/components/UiIcon.vue'
import { queueRuntime } from '@/services/queue-runtime'
import { sessionState } from '@/services/auth'
import { bootstrapState, loadBootstrap } from '@/stores/bootstrap'
import { selectionStorage } from '@/stores/selection'
import type { CloudPhoto, ProjectSummary } from '@/types/domain'
import { shortTime } from '@/utils/format'
import { syncTabBar } from '@/services/navigation'
import { STATUS_LABELS } from '@/services/photo-state'

const fallbackProject = ref<ProjectSummary>(selectionStorage.getProject())
const project = computed(() => bootstrapState.currentProject || fallbackProject.value)
const recent = computed<CloudPhoto[]>(() => bootstrapState.recentUploads)
const loading = ref(false)
const localRecent = computed(() => queueRuntime.state.photos.slice(0, 3))
const uniApi = uni

function localDayKey(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
const todayKey = computed(() => localDayKey(new Date().toISOString()))
const todayCaptureCount = computed(() => {
  const cloudIds = new Set<string>()
  let count = 0
  recent.value.forEach((photo) => {
    if (localDayKey(photo.captured_at || photo.created_at || photo.photo_date) === todayKey.value) {
      cloudIds.add(photo.photo_uuid)
      count += 1
    }
  })
  queueRuntime.state.photos.forEach((photo) => {
    if (!cloudIds.has(photo.photo_uuid) && localDayKey(photo.client_captured_at || photo.created_at) === todayKey.value) count += 1
  })
  return count
})
const pendingCount = computed(() => queueRuntime.pendingCount.value)
const requirementCount = computed(() => Number(project.value.requirement_count || 0))

async function loadHome() {
  if (loading.value) return
  const account = sessionState.account
  if (!account) return
  loading.value = true
  try {
    await loadBootstrap(account.id)
    fallbackProject.value = bootstrapState.currentProject || selectionStorage.getProject()
  } catch {
    fallbackProject.value = selectionStorage.getProject()
  } finally {
    loading.value = false
  }
}
function openProject() { uni.navigateTo({ url: '/pages/project/select' }) }
function openRequirements() {
  if (!selectionStorage.hasProject()) {
    uni.showModal({ title: '尚未同步工程', content: '请先在原电脑登录同一账号并同步工程。', showCancel: false })
    return
  }
  uni.navigateTo({ url: '/pages/requirements/index' })
}
function openQueue() { uni.switchTab({ url: '/pages/queue/index' }) }

onShow(() => {
  syncTabBar(0)
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
  <view class="page-shell home-page">
    <AppHeader :project-name="project.name" :online="queueRuntime.state.online" @select-project="openProject" />
    <view class="project-context">
      <text class="context-title">工作台</text>
    </view>
    <view class="summary-grid">
      <view class="summary-card"><text class="summary-number">{{ todayCaptureCount }}</text><text class="summary-label">今日采集</text></view>
      <button class="summary-card pressable" @tap="openQueue"><text class="summary-number" :class="{ warning: pendingCount > 0 }">{{ pendingCount }}</text><text class="summary-label">待上传</text></button>
      <button class="summary-card pressable" @tap="openRequirements"><text class="summary-number">{{ requirementCount || '—' }}</text><text class="summary-label">采集清单</text></button>
    </view>
    <view class="section-head"><text class="section-title">最近影像</text><button class="section-action pressable" @tap="uniApi.switchTab({ url: '/pages/library/index' })">查看全部</button></view>
    <view v-if="recent.length" class="recent-list">
      <button v-for="(photo, index) in recent" :key="photo.photo_uuid" class="recent-item pressable" @tap="uniApi.navigateTo({ url: `/pages/photo/detail?id=${photo.photo_uuid}` })">
        <image v-if="photo.thumb_url || photo.image_url" class="recent-thumb" :src="photo.thumb_url || photo.image_url" mode="aspectFill" lazy-load />
        <view v-else class="recent-thumb" :class="`scene-${index % 3}`"><text>{{ photo.unit_name?.slice(-3) || photo.other_node_name?.slice(-3) || '现场' }}</text></view>
        <view class="recent-copy"><text class="recent-title">{{ photo.title }}</text><text class="recent-meta">{{ photo.unit_name || photo.other_node_name }} · {{ photo.category === 'supervision' ? '监理影像' : photo.scope === 'other' ? '其它影像' : '施工影像' }}</text></view>
        <view class="recent-state"><UiIcon class="cloud-symbol" :name="photo.status === 'desktop_imported' ? 'check' : 'upload'" :size="17" /><text>{{ shortTime(photo.created_at) }}</text></view>
      </button>
    </view>
    <view v-else-if="localRecent.length" class="recent-list">
      <button v-for="photo in localRecent" :key="photo.photo_uuid" class="recent-item pressable" @tap="openQueue">
        <image v-if="photo.preview_path" class="recent-thumb" :src="photo.preview_path" mode="aspectFill" /><view v-else class="recent-thumb"><text>原图</text></view>
        <view class="recent-copy"><text class="recent-title">{{ photo.title }}</text><text class="recent-meta">{{ photo.draft.assignment?.unit_name || photo.draft.assignment?.other_node_name || '待匹配' }}</text></view><text class="status-chip">{{ STATUS_LABELS[photo.status] }}</text>
      </button>
    </view>
    <view v-else class="empty-state compact"><view class="empty-symbol"><UiIcon name="gallery" :size="27" /></view><text class="empty-title">还没有工程影像</text></view>
    <!-- #ifdef H5 --><H5TabBar :selected="0" :badge="queueRuntime.pendingCount.value" /><!-- #endif -->
  </view>
</template>

<style scoped>
.home-page { padding-bottom: calc(158rpx + var(--safe-bottom)); }
.project-context { margin-top: 0; }
.context-title { display: block; color: var(--text); font-size: 40rpx; font-weight: 700; line-height: 1.25; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; margin-top: var(--space-lg); overflow: hidden; border: 1rpx solid var(--line); border-radius: 22rpx; background: var(--surface); }
.summary-card { display: flex; flex-direction: column; align-items: center; justify-content: center; width: 100%; min-width: 0; min-height: 106rpx; margin: 0; padding: 16rpx 12rpx; border-right: 1rpx solid var(--line); text-align: center; background: transparent; }
.summary-card:last-child { border-right: 0; }
.summary-number { color: var(--text); font-size: 34rpx; font-weight: 700; line-height: 1.15; }
.summary-number.warning { color: var(--warning); }
.summary-label { margin-top: 6rpx; color: var(--muted); font-size: 22rpx; line-height: 1.2; }
.recent-list { display: grid; gap: 0; overflow: hidden; border: 1rpx solid var(--line); border-radius: 22rpx; background: var(--surface); }
.recent-item { display: grid; grid-template-columns: 108rpx 1fr auto; align-items: center; gap: 18rpx; width: 100%; min-height: 112rpx; padding: 12rpx 16rpx; border-bottom: 1rpx solid var(--line); text-align: left; background: transparent; }
.recent-item:last-child { border-bottom: 0; }
.recent-thumb { width: 108rpx; height: 86rpx; overflow: hidden; border-radius: 17rpx; background: #9fcfd8; }
view.recent-thumb { display: flex; align-items: flex-end; padding: 8rpx; color: #09262a; background: linear-gradient(155deg, #9cd7e3 0 38%, #d6c69e 39% 60%, #668876 61%); font-size: 20rpx; font-weight: 700; }
view.recent-thumb.scene-1 { background: linear-gradient(105deg, #86ccde 0 44%, #b5b9b4 45% 67%, #517c6d 68%); }
view.recent-thumb.scene-2 { background: linear-gradient(160deg, #9bdbe8 0 34%, #c5b98d 35% 61%, #6e8f69 62%); }
.recent-copy { min-width: 0; }
.recent-title { display: block; overflow: hidden; color: var(--text); font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.recent-meta { display: block; overflow: hidden; margin-top: 8rpx; color: var(--muted); font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
.recent-state { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4rpx; color: var(--primary-strong); font-size: 20rpx; }
.cloud-symbol { font-size: 29rpx; }
.empty-state.compact { min-height: 280rpx; }
</style>
