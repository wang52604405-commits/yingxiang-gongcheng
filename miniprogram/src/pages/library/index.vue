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
const selectedDestination = ref(selectionStorage.getDestination())
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

onShow(() => {
  syncTabBar(1)
  project.value = selectionStorage.getProject()
  selectedDestination.value = selectionStorage.getDestination()
  void loadPhotos()
})
onPullDownRefresh(() => loadPhotos(true))
onReachBottom(() => { void loadPhotos(false) })
</script>

<template>
  <view class="page-shell">
    <AppHeader :project-name="project.name" :online="queueRuntime.state.online" @select-project="uniApi.navigateTo({ url: '/pages/project/select' })" />
    <view class="title-row">
      <view>
        <text class="page-title">影像库</text>
        <text class="page-subtitle">按电脑端的工程层级查看。</text>
      </view>
      <button class="search-button pressable" aria-label="搜索工程部位" @tap="chooseDestination"><UiIcon name="search" :size="21" /></button>
    </view>

    <view class="segment library-segment">
      <button class="segment-button pressable" :class="{ active: scope === 'engineering' }" @tap="changeScope('engineering')">工程影像</button>
      <button class="segment-button pressable" :class="{ active: scope === 'other' }" @tap="changeScope('other')">其它影像</button>
    </view>

    <button class="path-card pressable" @tap="chooseDestination">
      <view class="path-copy">
        <text class="path-label">当前归档位置</text>
        <text class="path-title">{{ selectedDestination?.scope === scope ? selectedDestination.assignment.unit_name || selectedDestination.assignment.other_node_name : scope === 'engineering' ? '全部工程部位' : '全部其它影像' }}</text>
        <text class="path-code">{{ selectedDestination?.scope === scope ? selectedDestination.assignment.unit_code || selectedDestination.assignment.other_node_code : project.code }}</text>
      </view>
      <view class="path-arrow"><UiIcon name="chevron" :size="18" /></view>
    </button>

    <view class="section-head unit-head">
      <view>
        <text class="section-title">{{ scope === 'engineering' ? '工程照片' : '其它照片' }}</text>
        <text class="count-copy">共 {{ totalCount }} 张影像 · 已显示 {{ photos.length }} 张</text>
      </view>
    </view>

    <view v-if="scope === 'engineering'" class="segment category-segment">
      <button class="segment-button pressable" :class="{ active: category === 'construction' }" @tap="changeCategory('construction')">施工影像</button>
      <button class="segment-button pressable" :class="{ active: category === 'supervision' }" @tap="changeCategory('supervision')">监理影像</button>
    </view>

    <view v-if="loading && !photos.length" class="loading-inline"><view class="loading-spinner" /><text>正在读取影像</text></view>
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
    <text v-else-if="photos.length" class="all-loaded">已显示全部 {{ photos.length }} 张影像</text>
    <view v-else class="empty-state">
      <view class="empty-symbol"><UiIcon name="gallery" :size="27" /></view>
      <text class="empty-title">这里还没有影像</text>
      <text class="empty-copy">切换归档位置，或点击底部中间的“采集”添加现场照片。</text>
    </view>
    <!-- #ifdef H5 -->
    <H5TabBar :selected="1" :badge="queueRuntime.pendingCount.value" />
    <!-- #endif -->
  </view>
</template>

<style scoped>
.title-row { display: flex; align-items: center; justify-content: space-between; }
.search-button { display: grid; place-items: center; width: 72rpx; height: 72rpx; border: 1rpx solid var(--line); border-radius: 21rpx; color: var(--primary-strong); background: var(--surface); font-size: 36rpx; }
.library-segment { margin-top: 30rpx; }
.path-card { display: flex; align-items: center; justify-content: space-between; width: 100%; margin-top: 20rpx; padding: 22rpx 24rpx; border: 1rpx solid var(--line); border-radius: 24rpx; text-align: left; background: var(--surface); }
.path-copy { min-width: 0; }
.path-label { display: block; color: var(--muted); font-size: 21rpx; }
.path-title { display: block; overflow: hidden; margin-top: 7rpx; color: var(--text); font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.path-code { display: block; margin-top: 5rpx; color: var(--primary-strong); font-size: 20rpx; }
.path-arrow { display: grid; flex: 0 0 auto; place-items: center; width: 36rpx; height: 52rpx; color: var(--muted); }
.unit-head { margin-bottom: 18rpx; }
.count-copy { display: block; margin-top: 6rpx; color: var(--muted); font-size: 21rpx; }
.category-segment { margin-bottom: 20rpx; }
.gallery { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10rpx; }
.photo-tile { position: relative; display: block; width: 100%; min-width: 0; aspect-ratio: 1 / 1.14; overflow: hidden; border-radius: 18rpx; background: var(--surface); }
.tile-image, .tile-placeholder { width: 100%; height: 100%; }
.tile-placeholder { display: flex; align-items: flex-start; padding: 12rpx; color: #09262a; background: linear-gradient(155deg, #9cd7e3 0 38%, #d6c69e 39% 60%, #668876 61%); font-size: 20rpx; font-weight: 700; }
.tile-placeholder.tone-1 { background: linear-gradient(105deg, #86ccde 0 44%, #b5b9b4 45% 67%, #517c6d 68%); }
.tile-placeholder.tone-2 { background: linear-gradient(160deg, #9bdbe8 0 34%, #c5b98d 35% 61%, #6e8f69 62%); }
.tile-placeholder.tone-3 { background: linear-gradient(130deg, #a8dfe7 0 33%, #8d9d9b 34% 52%, #b79d70 53% 70%, #66866f 71%); }
.tile-overlay { position: absolute; left: 0; right: 0; bottom: 0; display: grid; gap: 4rpx; padding: 34rpx 12rpx 11rpx; color: #fff; text-align: left; background: linear-gradient(transparent, rgba(4, 17, 20, 0.88)); }
.tile-title { overflow: hidden; font-size: 21rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.tile-date { font-size: 20rpx; opacity: 0.76; }
.loading-inline { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 360rpx; color: var(--muted); font-size: 24rpx; }
.loading-inline .loading-spinner { width: 48rpx; height: 48rpx; margin-bottom: 18rpx; }
.load-more { display: flex; align-items: center; justify-content: center; width: 260rpx; min-height: 66rpx; margin: 24rpx auto 0; padding: 0 24rpx; border: 1rpx solid var(--line); border-radius: 20rpx; color: var(--primary-strong); background: var(--surface); font-size: 22rpx; line-height: 1.25; text-align: center; }
.all-loaded { display: block; padding: 26rpx 0 10rpx; color: var(--muted); text-align: center; font-size: 20rpx; }
</style>
