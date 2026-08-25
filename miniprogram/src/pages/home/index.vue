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

function openUpload(mode: 'direct' | 'auto') {
  selectionStorage.setUploadPreset({ scope: 'engineering', category: 'construction', mode })
  uni.switchTab({ url: '/pages/upload/index' })
}

function openProject() {
  uni.navigateTo({ url: '/pages/project/select' })
}

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

watch(() => sessionState.ready, (ready) => {
  if (ready && sessionState.account) void loadHome()
})
</script>

<template>
  <view class="page-shell">
    <AppHeader :project-name="project.name" :online="queueRuntime.state.online" @select-project="openProject" />

    <text class="page-title">现场工作台</text>
    <text class="page-subtitle">上传时先安全保存，电脑端自动接着整理。</text>

    <button class="capture-card pressable" @tap="openUpload('direct')">
      <view class="capture-icon"><UiIcon name="camera" :size="25" /></view>
      <view class="capture-copy">
        <text class="capture-title">拍摄工程影像</text>
        <text class="capture-subtitle">选择施工/监理与单元后直接拍摄</text>
      </view>
      <text class="capture-arrow">›</text>
    </button>

    <view class="quick-grid">
      <button class="quick-button pressable" @tap="openUpload('direct')">
        <UiIcon class="quick-symbol" name="camera" :size="19" />
        <text>现场拍照</text>
      </button>
      <button class="quick-button pressable" @tap="openUpload('auto')">
        <UiIcon class="quick-symbol" name="gallery" :size="19" />
        <text>批量自动匹配</text>
      </button>
    </view>

    <view class="section-head">
      <text class="section-title">最近上传</text>
      <button class="section-action pressable" @tap="uniApi.switchTab({ url: '/pages/library/index' })">查看全部</button>
    </view>

    <view v-if="recent.length" class="recent-list">
      <button v-for="(photo, index) in recent" :key="photo.photo_uuid" class="recent-item pressable" @tap="uniApi.navigateTo({ url: `/pages/photo/detail?id=${photo.photo_uuid}` })">
        <image v-if="photo.thumb_url || photo.image_url" class="recent-thumb" :src="photo.thumb_url || photo.image_url" mode="aspectFill" lazy-load />
        <view v-else class="recent-thumb" :class="`scene-${index % 3}`"><text>{{ photo.unit_name?.slice(-3) || photo.other_node_name?.slice(-3) || '现场' }}</text></view>
        <view class="recent-copy">
          <text class="recent-title">{{ photo.title }}</text>
          <text class="recent-meta">{{ photo.unit_name || photo.other_node_name }} · {{ photo.category === 'supervision' ? '监理影像' : photo.scope === 'other' ? '其它影像' : '施工影像' }}</text>
        </view>
        <view class="recent-state">
          <UiIcon class="cloud-symbol" :name="photo.status === 'desktop_imported' ? 'check' : 'upload'" :size="17" />
          <text>{{ shortTime(photo.created_at) }}</text>
        </view>
      </button>
    </view>

    <view v-else-if="localRecent.length" class="recent-list">
      <button v-for="photo in localRecent" :key="photo.photo_uuid" class="recent-item pressable" @tap="uniApi.switchTab({ url: '/pages/queue/index' })">
        <image v-if="photo.preview_path" class="recent-thumb" :src="photo.preview_path" mode="aspectFill" />
        <view v-else class="recent-thumb"><text>原图</text></view>
        <view class="recent-copy">
          <text class="recent-title">{{ photo.title }}</text>
          <text class="recent-meta">{{ photo.draft.assignment?.unit_name || photo.draft.assignment?.other_node_name || '等待自动匹配' }}</text>
        </view>
        <text class="status-chip">{{ STATUS_LABELS[photo.status] }}</text>
      </button>
    </view>

    <view v-else class="empty-state compact">
      <view class="empty-symbol"><UiIcon name="gallery" :size="27" /></view>
      <text class="empty-title">还没有上传记录</text>
      <text class="empty-copy">点击上方按钮拍摄第一张工程影像。</text>
    </view>
    <!-- #ifdef H5 -->
    <H5TabBar :selected="0" :badge="queueRuntime.pendingCount.value" />
    <!-- #endif -->
  </view>
</template>

<style scoped>
.capture-card { display: grid; grid-template-columns: 88rpx 1fr 34rpx; align-items: center; gap: 20rpx; width: 100%; min-height: 158rpx; margin-top: 38rpx; padding: 24rpx 28rpx; border-radius: 34rpx; color: #fff; text-align: left; background: linear-gradient(115deg, #197f79, #2db9aa); box-shadow: 0 20rpx 42rpx rgba(16, 137, 126, 0.22); }
.capture-icon { display: grid; place-items: center; width: 88rpx; height: 88rpx; border-radius: 25rpx; background: rgba(255, 255, 255, 0.13); font-size: 38rpx; }
.capture-copy { min-width: 0; }
.capture-title { display: block; font-size: 34rpx; font-weight: 700; }
.capture-subtitle { display: block; margin-top: 8rpx; font-size: 23rpx; opacity: 0.78; }
.capture-arrow { font-size: 46rpx; font-weight: 300; }
.quick-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18rpx; margin-top: 20rpx; }
.quick-button { display: flex; align-items: center; justify-content: center; gap: 14rpx; min-height: 86rpx; border: 1rpx solid var(--line); border-radius: 22rpx; color: var(--text); background: var(--surface); font-size: 26rpx; font-weight: 600; }
.quick-symbol { color: var(--primary-strong); font-size: 31rpx; }
.recent-list { display: grid; gap: 16rpx; }
.recent-item { display: grid; grid-template-columns: 108rpx 1fr auto; align-items: center; gap: 18rpx; width: 100%; min-height: 112rpx; padding: 12rpx 16rpx; border: 1rpx solid var(--line); border-radius: 22rpx; text-align: left; background: var(--surface); }
.recent-thumb { width: 108rpx; height: 86rpx; overflow: hidden; border-radius: 17rpx; background: #9fcfd8; }
view.recent-thumb { display: flex; align-items: flex-end; padding: 8rpx; color: #09262a; background: linear-gradient(155deg, #9cd7e3 0 38%, #d6c69e 39% 60%, #668876 61%); font-size: 18rpx; font-weight: 700; }
view.recent-thumb.scene-1 { background: linear-gradient(105deg, #86ccde 0 44%, #b5b9b4 45% 67%, #517c6d 68%); }
view.recent-thumb.scene-2 { background: linear-gradient(160deg, #9bdbe8 0 34%, #c5b98d 35% 61%, #6e8f69 62%); }
.recent-copy { min-width: 0; }
.recent-title { display: block; overflow: hidden; color: var(--text); font-size: 27rpx; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.recent-meta { display: block; overflow: hidden; margin-top: 8rpx; color: var(--muted); font-size: 21rpx; text-overflow: ellipsis; white-space: nowrap; }
.recent-state { display: flex; flex-direction: column; align-items: center; gap: 4rpx; color: var(--primary-strong); font-size: 19rpx; }
.cloud-symbol { font-size: 29rpx; }
.empty-state.compact { min-height: 300rpx; }
</style>
