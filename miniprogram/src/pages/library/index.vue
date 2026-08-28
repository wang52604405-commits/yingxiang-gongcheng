<script setup lang="ts">
import { ref } from 'vue'
import { onPullDownRefresh, onReachBottom, onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import H5TabBar from '@/components/H5TabBar.vue'
import UiIcon from '@/components/UiIcon.vue'
import { mobileApi } from '@/api/mobile'
import { queueRuntime } from '@/services/queue-runtime'
import { syncTabBar } from '@/services/navigation'
import { selectionStorage } from '@/stores/selection'
import type { CloudPhoto, PhotoCategory, Scope } from '@/types/domain'
import { shortDate } from '@/utils/format'

const project = ref(selectionStorage.getProject())
const scope = ref<Scope>('engineering')
const category = ref<PhotoCategory>('construction')
const photos = ref<CloudPhoto[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const nextCursor = ref('')
const totalCount = ref(0)
const selectedDestination = ref(selectionStorage.getLibraryFilter())
const uniApi = uni
let requestVersion = 0

async function loadPhotos(reset = true) {
  if (!project.value.id) {
    photos.value = []
    totalCount.value = 0
    nextCursor.value = ''
    loading.value = false
    loadingMore.value = false
    uni.stopPullDownRefresh()
    return
  }
  if (!reset && (loadingMore.value || !nextCursor.value)) return
  const version = reset ? ++requestVersion : requestVersion
  if (reset) loading.value = true
  else loadingMore.value = true
  try {
    const response = await mobileApi.photos({
      project_id: project.value.id,
      scope: scope.value,
      category: scope.value === 'engineering' ? category.value : undefined,
      unit_code: scope.value === 'engineering' ? selectedDestination.value?.assignment.unit_code : undefined,
      other_node_code: scope.value === 'other' ? selectedDestination.value?.assignment.other_node_code : undefined,
      cursor: reset ? undefined : nextCursor.value,
      limit: 60,
    })
    if (version !== requestVersion) return
    const incoming: CloudPhoto[] = response.photos || []
    if (reset) photos.value = incoming
    else {
      const existing = new Set(photos.value.map((photo) => photo.photo_uuid))
      photos.value = [...photos.value, ...incoming.filter((photo) => !existing.has(photo.photo_uuid))]
    }
    nextCursor.value = response.next_cursor || ''
    totalCount.value = response.total
  } catch (error) {
    if (version === requestVersion) uni.showToast({ title: error instanceof Error ? error.message : '影像加载失败', icon: 'none' })
  } finally {
    if (version === requestVersion) {
      loading.value = false
      loadingMore.value = false
      uni.stopPullDownRefresh()
    }
  }
}

function changeScope(next: Scope) {
  scope.value = next
  void loadPhotos()
}

function changeCategory(next: PhotoCategory) {
  category.value = next
  void loadPhotos()
}

function chooseDestination() {
  uni.navigateTo({ url: `/pages/destination/select?scope=${scope.value}&return=library` })
}

function clearDestination() {
  selectionStorage.clearLibraryFilter()
  selectedDestination.value = null
  void loadPhotos()
}

onShow(() => {
  syncTabBar(1)
  project.value = selectionStorage.getProject()
  selectedDestination.value = selectionStorage.getLibraryFilter()
  void loadPhotos()
})
onPullDownRefresh(() => loadPhotos(true))
onReachBottom(() => { void loadPhotos(false) })
</script>

<template>
  <view class="page-shell">
    <AppHeader :project-name="project.name" :online="queueRuntime.state.online" @select-project="uniApi.navigateTo({ url: '/pages/project/select' })" />
    <text class="page-title">影像库</text>

    <view class="library-controls card">
      <view class="segment library-segment">
        <button class="segment-button pressable" :class="{ active: scope === 'engineering' }" @tap="changeScope('engineering')">工程影像</button>
        <button class="segment-button pressable" :class="{ active: scope === 'other' }" @tap="changeScope('other')">其它影像</button>
      </view>
      <view class="path-row">
      <button class="path-card pressable" @tap="chooseDestination">
        <view class="path-copy"><UiIcon name="folder" :size="18" /><text class="path-title">{{ selectedDestination?.scope === scope ? selectedDestination.assignment.unit_name || selectedDestination.assignment.other_node_name : scope === 'engineering' ? '选择单元' : '选择目录' }}</text></view>
        <view class="path-arrow"><UiIcon name="chevron" :size="18" /></view>
      </button>
      <button v-if="selectedDestination?.scope === scope" class="clear-filter pressable" @tap="clearDestination">查看全部</button>
      </view>
      <view v-if="scope === 'engineering'" class="segment category-segment">
        <button class="segment-button pressable" :class="{ active: category === 'construction' }" @tap="changeCategory('construction')">施工影像</button>
        <button class="segment-button pressable" :class="{ active: category === 'supervision' }" @tap="changeCategory('supervision')">监理影像</button>
      </view>
    </view>

    <view class="section-head unit-head"><text class="section-title">{{ scope === 'engineering' ? '工程照片' : '其它照片' }}</text><text class="count-copy">{{ totalCount }} 张</text></view>

    <view v-if="loading && !photos.length" class="loading-inline"><view class="loading-spinner" /><text>加载中…</text></view>
    <view v-else-if="photos.length" class="gallery">
      <button v-for="(photo, index) in photos" :key="photo.photo_uuid" class="photo-tile pressable" @tap="uniApi.navigateTo({ url: `/pages/photo/detail?id=${photo.photo_uuid}` })">
        <image v-if="photo.thumb_url || photo.image_url" class="tile-image" :src="photo.thumb_url || photo.image_url" mode="aspectFill" lazy-load />
        <view v-else class="tile-placeholder" :class="`tone-${index % 4}`"><text>{{ photo.unit_name?.slice(-3) || photo.other_node_name?.slice(-3) || '现场' }}</text></view>
        <view class="tile-overlay">
          <text class="tile-title">{{ photo.title }}</text>
          <text class="tile-date">{{ shortDate(photo.photo_date) }}</text>
        </view>
      </button>
    </view>
    <button v-if="photos.length && nextCursor" class="load-more pressable" :disabled="loadingMore" @tap="loadPhotos(false)">{{ loadingMore ? '正在加载…' : '继续加载更多' }}</button>
    <view v-if="!loading && !photos.length" class="empty-state">
      <view class="empty-symbol"><UiIcon name="gallery" :size="27" /></view>
      <text class="empty-title">这里还没有影像</text>
    </view>
    <!-- #ifdef H5 -->
    <H5TabBar :selected="1" :badge="queueRuntime.pendingCount.value" />
    <!-- #endif -->
  </view>
</template>

<style scoped>
.library-controls { margin-top: var(--space-lg); padding: 12rpx; }
.library-segment { margin: 0; }
.path-row { display: flex; align-items: center; gap: 8rpx; margin: 8rpx 0; }
.path-card { display: flex; flex: 1; min-width: 0; align-items: center; justify-content: space-between; min-height: 88rpx; padding: 0 14rpx; border-radius: 16rpx; text-align: left; background: transparent; }
.clear-filter { display: inline-flex; flex: 0 0 auto; align-items: center; justify-content: center; min-height: 40px; padding: 0 14rpx; color: var(--primary-strong); font-size: 22rpx; }
.path-copy { display: flex; align-items: center; min-width: 0; gap: 14rpx; color: var(--primary-strong); }
.path-title { display: block; overflow: hidden; color: var(--text); font-size: 26rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.path-arrow { display: grid; flex: 0 0 auto; place-items: center; width: 36rpx; height: 52rpx; color: var(--muted); }
.count-copy { display: block; margin-top: 6rpx; color: var(--muted); font-size: 22rpx; }
.category-segment { margin: 0; }
.gallery { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12rpx; }
.photo-tile { position: relative; display: block; width: 100%; min-width: 0; aspect-ratio: 4 / 3; overflow: hidden; border-radius: 18rpx; background: var(--surface); }
.tile-image, .tile-placeholder { width: 100%; height: 100%; }
.tile-placeholder { display: flex; align-items: flex-start; padding: 12rpx; color: #09262a; background: linear-gradient(155deg, #9cd7e3 0 38%, #d6c69e 39% 60%, #668876 61%); font-size: 20rpx; font-weight: 700; }
.tile-placeholder.tone-1 { background: linear-gradient(105deg, #86ccde 0 44%, #b5b9b4 45% 67%, #517c6d 68%); }
.tile-placeholder.tone-2 { background: linear-gradient(160deg, #9bdbe8 0 34%, #c5b98d 35% 61%, #6e8f69 62%); }
.tile-placeholder.tone-3 { background: linear-gradient(130deg, #a8dfe7 0 33%, #8d9d9b 34% 52%, #b79d70 53% 70%, #66866f 71%); }
.tile-overlay { position: absolute; left: 0; right: 0; bottom: 0; display: grid; gap: 4rpx; padding: 34rpx 12rpx 11rpx; color: #fff; text-align: left; background: linear-gradient(transparent, rgba(4, 17, 20, 0.88)); }
.tile-title { overflow: hidden; font-size: 23rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.tile-date { font-size: 21rpx; opacity: 0.8; }
.loading-inline { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 360rpx; color: var(--muted); font-size: 24rpx; }
.loading-inline .loading-spinner { width: 48rpx; height: 48rpx; margin-bottom: 18rpx; }
.load-more { display: flex; align-items: center; justify-content: center; width: 260rpx; min-height: 40px; margin: 24rpx auto 0; padding: 0 24rpx; border: 1rpx solid var(--line); border-radius: 20rpx; color: var(--primary-strong); background: var(--surface); font-size: 23rpx; line-height: 1.25; text-align: center; }
</style>
