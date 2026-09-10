<script setup lang="ts">
import { usePageTheme } from '@/services/theme'
const themeStyle = usePageTheme()
import { setWatermarkContext } from '@/services/watermark-context'
import DeletePasswordDialog from '@/components/DeletePasswordDialog.vue'
import { photoActions } from '@/services/photo-actions'
import { consumePhotoEditDestination } from '@/services/destination-history'
import { canCaptureProject } from '@/services/project-membership'
import { computed, reactive, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { queueRuntime } from '@/services/queue-runtime'
import { buildPhotoDetailRows, resolvePhotoHierarchy, type PhotoHierarchy } from '@/services/photo-detail'
import type { Assignment, CloudPhoto, LocalPhoto, ProjectSummary } from '@/types/domain'
import { sessionState } from '@/services/auth'
import { bootstrapState } from '@/stores/bootstrap'
import { selectionStorage } from '@/stores/selection'

const detailOwner = ref('')
const detailProject = ref('')
const photoId = ref('')
const local = ref<LocalPhoto | null>(null)
const cloud = ref<CloudPhoto | null>(null)
const loading = ref(true)
const projectName = ref('')
const hierarchy = ref<PhotoHierarchy>({})
const imageUrl = computed(() => local.value?.preview_path || cloud.value?.image_url || cloud.value?.thumb_url || '')
const localActor = computed(() => sessionState.account?.display_name || sessionState.account?.username || '')
const editing = ref(false)
const changing = ref(false)
const editError = ref('')
const deleteVisible = ref(false)
const deleteError = ref('')
const editForm = reactive({ title: '', photo_date: '', assignment: undefined as Assignment | undefined })
let choosingAssignment = false
const currentScope = computed(() => local.value?.draft.scope || cloud.value?.scope || 'engineering')
const canEdit = computed(() => {
  const project = selectionStorage.getProject() as ProjectSummary
  if (!canCaptureProject(project)) return false
  if (cloud.value) {
    return ['owner', 'admin'].includes(project.access_role || 'owner')
      || String(cloud.value.uploaded_by_account_id || '') === String(sessionState.account?.id || '')
  }
  if (local.value) {
    return String(local.value.owner_account_id || '') === String(sessionState.account?.id || '')
      && local.value.status !== 'uploading'
  }
  return false
})
const detailRows = computed(() => {
  const photoDate = local.value?.photo_date || cloud.value?.photo_date || ''
  return buildPhotoDetailRows({
    local: cloud.value ? null : local.value,
    cloud: cloud.value,
    projectName: projectName.value,
    hierarchy: hierarchy.value,
    localActor: localActor.value,
  }).map((row) => row.key === 'captured_at' && photoDate
    ? { ...row, label: '拍摄日期', value: photoDate }
    : row)
})
function stillCurrent() { return detailOwner.value === selectionStorage.getOwner() && detailProject.value === String(selectionStorage.getProject().id) }
function startEditing() {
  if (!canEdit.value) return
  editForm.title = cloud.value?.title || local.value?.title || ''
  editForm.photo_date = cloud.value?.photo_date || local.value?.photo_date || ''
  editForm.assignment = undefined
  editError.value = ''
  editing.value = true
}
function chooseAssignment() {
  if (changing.value || !stillCurrent()) return
  consumePhotoEditDestination(detailOwner.value, detailProject.value)
  choosingAssignment = true
  uni.navigateTo({ url: `/pages/destination/select?scope=${currentScope.value}&return=photo-edit` })
}
async function saveInfo() {
  if (!stillCurrent() || !canEdit.value || changing.value) return
  if (!editForm.photo_date) {
    editError.value = '请选择照片日期'
    return
  }
  changing.value = true
  editError.value = ''
  try {
    if (cloud.value) {
      const result = await photoActions.edit(photoId.value, detailProject.value, { ...editForm })
      if (!stillCurrent()) return
      cloud.value = result
      queueRuntime.applyCloudPhotoInfo(photoId.value, { title: result.title, photo_date: result.photo_date, assignment: editForm.assignment })
    } else if (local.value) {
      queueRuntime.applyCloudPhotoInfo(photoId.value, { title: editForm.title.trim(), photo_date: editForm.photo_date, assignment: editForm.assignment })
      local.value.title = editForm.title.trim()
      local.value.photo_date = editForm.photo_date
      local.value.draft.title = editForm.title.trim()
      local.value.draft.photo_date = editForm.photo_date
      if (editForm.assignment) local.value.draft.assignment = { ...editForm.assignment }
    }
    editing.value = false
    await loadProjectDetails()
    uni.showToast({ title: cloud.value ? '已保存，电脑端将同步' : '已保存到待上传照片', icon: 'success' })
  } catch (error) {
    editError.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    changing.value = false
  }
}
async function confirmDelete(password: string) {
  if (!stillCurrent() || !canEdit.value || changing.value || !cloud.value) return
  changing.value = true
  deleteError.value = ''
  try {
    await photoActions.delete(photoId.value, detailProject.value, password)
    if (!stillCurrent()) return
    queueRuntime.markCloudPhotoDeleted(photoId.value)
    deleteVisible.value = false
    uni.showToast({ title: '照片已删除', icon: 'success' })
    uni.navigateBack()
  } catch (error) {
    deleteError.value = error instanceof Error ? error.message : '删除失败'
  } finally {
    changing.value = false
  }
}

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
  local.value = queueRuntime.state.photos.find((photo) => photo.photo_uuid === photoId.value && !photo.deleted_at) || null
  if (!local.value || !['local_ready', 'uploading'].includes(local.value.status)) {
    try {
      const response = await mobileApi.photo(photoId.value)
      cloud.value = response.photo
    } catch (error) {
      if (!local.value) uni.showModal({ title: '影像读取失败', content: error instanceof Error ? error.message : '请稍后重试', showCancel: false })
    }
  }
  if (local.value || cloud.value) await loadProjectDetails()
  loading.value = false
}

function preview() {
  if (imageUrl.value) uni.previewImage({ current: imageUrl.value, urls: [imageUrl.value] })
}

function openWatermark() {
  const owner = selectionStorage.getOwner()
  const currentProjectId = String(selectionStorage.getProject().id || '')
  if (!owner || !currentProjectId || String(sessionState.account?.id || '') !== owner) return
  if (owner !== detailOwner.value || currentProjectId !== detailProject.value) {
    uni.showToast({ title: '账号或工程已切换，请重新打开照片', icon: 'none' })
    return
  }
  if (local.value && String(local.value.owner_account_id) !== owner) {
    uni.showToast({ title: '账号已切换，请重新打开照片', icon: 'none' })
    return
  }
  const sourcePath = local.value?.original_path || imageUrl.value
  if (!sourcePath) {
    uni.showToast({ title: '照片暂时无法读取', icon: 'none' })
    return
  }
  try {
    setWatermarkContext(owner, currentProjectId, {
      sourcePath,
      sourceQuality: local.value?.original_path ? 'original' : 'preview',
      sourceKind: 'detail',
      capturedAt: local.value?.client_captured_at || cloud.value?.captured_at || '',
      unitProjectName: local.value?.draft.assignment?.unit_project_name || cloud.value?.unit_project_name || '',
      partName: local.value?.draft.assignment?.part_name || cloud.value?.part_name || '',
      unitName: local.value?.draft.assignment?.unit_name || cloud.value?.unit_name || '',
      scope: currentScope.value,
      category: local.value?.draft.category || cloud.value?.category,
      sitePart: [local.value?.draft.assignment?.unit_name || cloud.value?.unit_name, local.value?.draft.assignment?.process_name || cloud.value?.process_name].filter(Boolean).join(' / '),
      project: projectName.value,
      title: local.value?.title || cloud.value?.title || '',
      photographer: cloud.value?.photographer || local.value?.draft.photographer || '',
      photoDate: local.value?.photo_date || cloud.value?.photo_date || '',
    })
    uni.navigateTo({ url: '/pages/photo/watermark' })
  } catch (reason) {
    uni.showToast({ title: reason instanceof Error ? reason.message : '打开水印失败', icon: 'none' })
  }
}

onShow(() => {
  if (choosingAssignment) {
    choosingAssignment = false
    if (stillCurrent()) {
      const picked = consumePhotoEditDestination(detailOwner.value, detailProject.value)
      if (picked && picked.scope === currentScope.value) editForm.assignment = picked.assignment
    }
  }
})
onLoad((query) => {
  detailOwner.value = selectionStorage.getOwner()
  detailProject.value = String(selectionStorage.getProject().id || '')
  photoId.value = String(query?.id || '')
  void load()
})
</script>

<template>
  <page-meta :page-style="themeStyle" />
  <view class="page-shell no-tabs detail-page" :style="themeStyle">
    <PageHeader title="照片详情" />
    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">加载中…</text></view>
    <template v-else-if="local || cloud">
      <button class="photo-preview pressable" @tap="preview">
        <image v-if="imageUrl" :src="imageUrl" mode="aspectFit" />
        <view v-else class="preview-placeholder">暂无预览</view>
      </button>
      <button v-if="imageUrl || local?.original_path" class="watermark-button primary-button pressable" @tap="openWatermark">{{ local?.original_path ? '保存水印照片' : '保存水印预览' }}</button>
      <view v-if="canEdit" class="photo-actions">
        <button class="secondary-button photo-action-button edit-action pressable" @tap="startEditing">编辑照片信息</button>
        <button v-if="cloud" class="photo-action-button danger-outline-button pressable" @tap="deleteError = ''; deleteVisible = true">删除照片</button>
        <button v-else class="photo-action-button pending-action" disabled>待上传照片</button>
      </view>
      <view v-if="editing" class="detail-card edit-panel card">
        <text class="field-label">照片名称</text>
        <input v-model="editForm.title" class="input" maxlength="200" :disabled="changing" />
        <text class="field-label date-label">照片日期</text>
        <picker mode="date" :value="editForm.photo_date" :disabled="changing" @change="editForm.photo_date = $event.detail.value">
          <view class="input date-picker-value">
            <text>{{ editForm.photo_date || '选择照片日期' }}</text>
            <text class="date-arrow">›</text>
          </view>
        </picker>
        <button class="secondary-button" :disabled="changing" @tap="chooseAssignment">{{ editForm.assignment?.unit_name || editForm.assignment?.other_node_name || '更改工程部位' }}</button>
        <text v-if="editError" class="edit-error">{{ editError }}</text>
        <view class="photo-actions"><button :disabled="changing" @tap="editing = false">取消</button><button class="primary-button" :disabled="changing" @tap="saveInfo">{{ changing ? '保存中…' : '保存信息' }}</button></view>
      </view>
      <view class="detail-card card">
        <view v-for="row in detailRows" :key="row.key" class="detail-row">
          <text>{{ row.label }}</text>
          <text :class="{ 'status-value': row.accent }">{{ row.value }}</text>
        </view>
      </view>
    </template>
    <DeletePasswordDialog :visible="deleteVisible" :busy="changing" :error="deleteError" @close="deleteVisible = false" @confirm="confirmDelete" />
  </view>
</template>

<style scoped>
.detail-page { padding-bottom: calc(48rpx + var(--safe-bottom)); }
.photo-preview { display: grid; place-items: center; width: 100%; height: 510rpx; overflow: hidden; border: 1rpx solid var(--line); border-radius: 28rpx; background: #071215; }
.photo-preview image { width: 100%; height: 100%; }
.preview-placeholder { color: var(--muted); font-size: 24rpx; }
.watermark-button { margin-top: 24rpx; min-height: 92rpx; font-size: 28rpx; }
.photo-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16rpx; align-items: stretch; margin-top: 18rpx; }
.photo-actions button { display: flex; align-items: center; justify-content: center; width: 100%; min-width: 0; min-height: 88rpx; padding: 14rpx 18rpx; border-radius: 20rpx; font-size: 25rpx; font-weight: 600; line-height: 1.25; }
.photo-action-button { box-shadow: none; }
.edit-action { border-color: var(--primary-strong); color: var(--primary-strong); }
.danger-outline-button { border: 1rpx solid var(--danger); color: var(--danger); background: var(--surface); }
.pending-action { border: 1rpx solid var(--line); color: var(--muted); background: var(--surface-2); opacity: .8; }
.edit-panel { padding: 24rpx !important; }
.edit-panel .input { min-height: 48px; }
.edit-panel > button { margin-top: 20rpx; font-size: 25rpx; }
.date-label { margin-top: 22rpx; }
.date-picker-value { display: flex; align-items: center; justify-content: space-between; color: var(--text); }
.date-arrow { color: var(--muted); font-size: 36rpx; line-height: 1; }
.edit-error { display: block; margin-top: 12rpx; color: var(--danger); }
.detail-card { overflow: hidden; margin-top: 24rpx; padding: 0 22rpx; }
.detail-row { display: grid; grid-template-columns: 174rpx 1fr; gap: 18rpx; padding: 23rpx 0; border-bottom: 1rpx solid var(--line); line-height: 1.5; }
.detail-row:last-child { border-bottom: 0; }
.detail-row > text:first-child { color: var(--muted); font-size: 24rpx; }
.detail-row > text:last-child { color: var(--text); font-size: 27rpx; text-align: right; word-break: break-all; }
.detail-row .status-value { color: var(--primary-strong); }
</style>
