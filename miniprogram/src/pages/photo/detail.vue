<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { queueRuntime } from '@/services/queue-runtime'
import { buildPhotoDetailRows, resolvePhotoHierarchy, type PhotoHierarchy } from '@/services/photo-detail'
import type { CloudPhoto, LocalPhoto, ProjectSummary } from '@/types/domain'
import { sessionState } from '@/services/auth'
import { bootstrapState } from '@/stores/bootstrap'
import { selectionStorage } from '@/stores/selection'

const photoId = ref('')
const local = ref<LocalPhoto | null>(null)
const cloud = ref<CloudPhoto | null>(null)
const loading = ref(true)
const projectName = ref('')
const hierarchy = ref<PhotoHierarchy>({})
const imageUrl = computed(() => local.value?.preview_path || cloud.value?.image_url || cloud.value?.thumb_url || '')
const localActor = computed(() => sessionState.account?.display_name || sessionState.account?.username || '')
const detailRows = computed(() => buildPhotoDetailRows({
  local: local.value,
  cloud: cloud.value,
  projectName: projectName.value,
  hierarchy: hierarchy.value,
  localActor: localActor.value,
}))

function photoProjectId(): string {
  return local.value?.draft.project_id || cloud.value?.project_id || ''
}

function knownProjects(): ProjectSummary[] {
  const selected = selectionStorage.getProject() as ProjectSummary
  return [...bootstrapState.projects, ...(selected?.id ? [selected] : [])]
}

function knownProject(projectId: string): ProjectSummary | undefined {
  if (!projectId) return undefined
  return knownProjects().find((project) => String(project.id) === projectId)
}

async function loadProjectDetails() {
  const projectId = photoProjectId() || String(selectionStorage.getProject()?.id || '')
  const cachedProject = knownProject(projectId)
  projectName.value = local.value?.draft.project_name || cloud.value?.project_name || cachedProject?.name || ''
  if (!projectId) return
  try {
    const response = await mobileApi.projectTree(projectId)
    projectName.value = response.project.name || projectName.value
    const unitCode = local.value?.draft.assignment?.unit_code || cloud.value?.unit_code || ''
    hierarchy.value = resolvePhotoHierarchy(response.nodes, unitCode)
  } catch {
    // 层级补全失败不影响本地照片和已有字段的查看。
  }
}

async function load() {
  queueRuntime.hydrate()
  local.value = queueRuntime.state.photos.find((photo) => photo.photo_uuid === photoId.value) || null
  if (!local.value) {
    try {
      const response = await mobileApi.photo(photoId.value)
      cloud.value = response.photo
    } catch (error) {
      uni.showModal({ title: '影像读取失败', content: error instanceof Error ? error.message : '请稍后重试', showCancel: false })
    }
  }
  if (local.value || cloud.value) await loadProjectDetails()
  loading.value = false
}

function preview() {
  if (imageUrl.value) uni.previewImage({ current: imageUrl.value, urls: [imageUrl.value] })
}

onLoad((query) => {
  photoId.value = String(query?.id || '')
  void load()
})
</script>

<template>
  <view class="page-shell no-tabs detail-page">
    <PageHeader title="照片详情" />
    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">加载中…</text></view>
    <template v-else-if="local || cloud">
      <button class="photo-preview pressable" @tap="preview">
        <image v-if="imageUrl" :src="imageUrl" mode="aspectFit" />
        <view v-else class="preview-placeholder">暂无预览</view>
      </button>
      <view class="detail-card card">
        <view v-for="row in detailRows" :key="row.key" class="detail-row">
          <text>{{ row.label }}</text>
          <text :class="{ 'status-value': row.accent }">{{ row.value }}</text>
        </view>
      </view>
    </template>
  </view>
</template>

<style scoped>
.detail-page { padding-bottom: calc(48rpx + var(--safe-bottom)); }
.photo-preview { display: grid; place-items: center; width: 100%; height: 510rpx; overflow: hidden; border-radius: 28rpx; background: #071215; }
.photo-preview image { width: 100%; height: 100%; }
.preview-placeholder { color: var(--muted); font-size: 24rpx; }
.detail-card { overflow: hidden; margin-top: 24rpx; padding: 0 22rpx; }
.detail-row { display: grid; grid-template-columns: 174rpx 1fr; gap: 18rpx; padding: 23rpx 0; border-bottom: 1rpx solid var(--line); line-height: 1.5; }
.detail-row:last-child { border-bottom: 0; }
.detail-row > text:first-child { color: var(--muted); font-size: 24rpx; }
.detail-row > text:last-child { color: var(--text); font-size: 27rpx; text-align: right; word-break: break-all; }
.detail-row .status-value { color: var(--primary-strong); }
</style>
