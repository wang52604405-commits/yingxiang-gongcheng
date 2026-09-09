<script setup lang="ts">
import { setWatermarkContext } from '@/services/watermark-context'
import { consumePhotoEditDestination, flattenDestinations, reconcileDestination, destinationLabel as fullDestinationLabel } from '@/services/destination-history'
import { captureDraftStorage, captureOverrides, localDate, type CaptureItem } from '@/services/capture-draft'
import { loadDestinationTree } from '@/services/destination-tree'
import { sessionState } from '@/services/auth'
import { persistCaptureOriginal, discardCaptureOriginal, listCaptureOriginals } from '@/services/capture-draft-files'
import { parseJpegExif, getSourceFileSize } from '@/services/image-compression'
import { readFilePrefix } from '@/services/sha256'
import { computed, ref, reactive, watch } from 'vue'
import { onLoad, onShow, onHide, onUnload } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import UiIcon from '@/components/UiIcon.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import { queueRuntime } from '@/services/queue-runtime'
import { chooseCaptureSource, type CaptureSource } from '@/services/capture-entry'
import { choosePhotoPaths } from '@/services/media-picker'
import { selectionStorage } from '@/stores/selection'
import type { ProjectNode, CaptureRequirementRef, PhotoCategory, Scope, UploadDraft, UploadMode } from '@/types/domain'
import { formatBytes } from '@/utils/format'
import { canCaptureProject, capturePermissionMessage } from '@/services/project-membership'
import { archiveInfoIssues, isArchiveInfoComplete } from '@/services/archive-info'

const project = ref(selectionStorage.getProject())
const scope = ref<Scope>('engineering')
const category = ref<PhotoCategory>('construction')
const mode = ref<UploadMode>('direct')
const requirement = ref<CaptureRequirementRef | null>(null)
const destination = ref(selectionStorage.getDestination())
const source = ref<CaptureSource>('camera')
const items = ref<CaptureItem[]>([])
const pickedPaths = computed(() => items.value.map(item => item.path))
const batchTitle = ref('')
const photographer = ref('')
const selected = ref<number[]>([])
const editing = ref(false)
const editor = reactive({ title: '', photographer: '', date: '' })
const scopeOwner = ref('')
const scopeProject = ref('')
const restoring = ref(false)
const showAdvanced = ref(false)
const tree = ref<ProjectNode[]>([])
let treeRequest = 0
async function refreshTree() {
  const request = ++treeRequest
  const id = String(project.value.id)
  const requestedScope = scope.value
  tree.value = []
  try {
    const response = await loadDestinationTree(id, requestedScope)
    if (request === treeRequest && id === String(project.value.id) && requestedScope === scope.value) tree.value = response.nodes || []
  } catch { /* Selector presents a recoverable load error; offline drafts remain intact. */ }
}
const currentProcesses = computed(() => flattenDestinations(tree.value).find(node => node.type === 'unit' && node.code === destination.value?.assignment.unit_code && node.assignment.part_code === destination.value?.assignment.part_code && node.assignment.unit_project_code === destination.value?.assignment.unit_project_code)?.processes || [])
function chooseProcess(process: string) {
  if (!destination.value) return
  destination.value = { ...destination.value, assignment: { ...destination.value.assignment, process_name: process } }
  selectionStorage.setDestination(destination.value)
}

const draftWarning = ref('')
const commonTitles = ['钢筋安装', '模板验收', '混凝土浇筑', '隐蔽验收', '施工前', '施工后']
const missingDates = computed(() => items.value.filter(item => !captureOverrides(item, batchTitle.value, photographer.value).photo_date).length)
const selectedLabel = computed(() => selected.value.length ? `已选 ${selected.value.length} 张` : '选择照片可单独修改')
function persistDraft() {
  if (restoring.value || !scopeOwner.value || !scopeProject.value) return
  try {
    captureDraftStorage.save(scopeOwner.value, scopeProject.value, { items: items.value, title: batchTitle.value, photographer: photographer.value, draft: archiveDraft.value })
    draftWarning.value = ''
  } catch { draftWarning.value = '草稿保存失败，请保留当前页面并重试' }
}
function restoreDraft() {
  const owner = selectionStorage.getOwner()
  const projectId = String(project.value.id || '')
  if (scopeOwner.value === owner && scopeProject.value === projectId) return
  restoring.value = true
  scopeOwner.value = owner
  scopeProject.value = projectId
  selected.value = []
  editing.value = false
  const saved = captureDraftStorage.read(owner, projectId)
  queueRuntime.hydrate()
  const accepted = new Set(queueRuntime.state.photos.filter(photo => photo.owner_account_id === owner && photo.draft.project_id === projectId).map(photo => photo.draft.capture_item_id))
  items.value = (saved?.items || []).filter(item => !accepted.has(item.path))
  for (const recovered of listCaptureOriginals(owner, projectId)) {
    if (!accepted.has(recovered.originalPath) && !items.value.some(item => item.path === recovered.originalPath)) {
      items.value.push({ path: recovered.originalPath, sourcePath: recovered.originalPath, size: recovered.originalSize, date: '', source: 'album', overrides: {} })
    }
  }
  batchTitle.value = saved?.title || ''
  photographer.value = saved?.photographer || ''
  if (saved) {
    scope.value = saved.draft.scope
    category.value = saved.draft.category || 'construction'
    mode.value = saved.draft.mode
    requirement.value = saved.draft.requirement || null
    destination.value = saved.draft.assignment ? { scope: saved.draft.scope, assignment: saved.draft.assignment } : null
    if (destination.value) selectionStorage.setDestination(destination.value)
    savePreset()
  }
  restoring.value = false
}
async function reuseLast() {
  if (choosing.value || submitting.value) return
  const owner = scopeOwner.value
  const projectId = scopeProject.value
  const last = captureDraftStorage.last(scopeOwner.value, scopeProject.value)
  if (!last) { uni.showToast({ title: '还没有上一批记录', icon: 'none' }); return }
  let validated = null
  if (last.draft.assignment) {
    try {
      const response = await loadDestinationTree(String(project.value.id), last.draft.scope, true)
      validated = reconcileDestination({ scope: last.draft.scope, assignment: last.draft.assignment }, flattenDestinations(response.nodes || []))
    } catch { uni.showToast({ title: '暂时无法核对工程部位，请稍后重试', icon: 'none' }); return }
    if (!validated) { uni.showToast({ title: '上一批部位已变更，请重新选择', icon: 'none' }); return }
  }
  if (owner !== selectionStorage.getOwner() || projectId !== String(selectionStorage.getProject().id)) return
  if (scope.value !== last.draft.scope) items.value.forEach(item => { delete item.overrides.assignment })
  scope.value = last.draft.scope
  category.value = last.draft.category || 'construction'
  mode.value = last.draft.mode
  requirement.value = last.draft.requirement || null
  destination.value = validated
  if (destination.value) selectionStorage.setDestination(destination.value)
  batchTitle.value = last.title
  photographer.value = last.photographer
  savePreset()
  persistDraft()
}
function togglePhoto(index: number) {
  selected.value = selected.value.includes(index) ? selected.value.filter(value => value !== index) : [...selected.value, index]
}
function editSelected() {
  if (!selected.value.length) return
  const first = captureOverrides(items.value[selected.value[0]], batchTitle.value, photographer.value)
  editor.title = selected.value.length === 1 ? first.title || '' : ''
  editor.photographer = selected.value.length === 1 ? first.photographer || '' : ''
  editor.date = selected.value.length === 1 ? first.photo_date || '' : ''
  editing.value = true
}
function saveEdits() {
  for (const index of selected.value) {
    const item = items.value[index]
    if (!item) continue
    if (editor.title.trim()) item.overrides.title = editor.title.trim()
    if (editor.photographer.trim()) item.overrides.photographer = editor.photographer.trim()
    if (editor.date) item.overrides.photo_date = editor.date
  }
  editing.value = false
  persistDraft()
}
function resetSelected() {
  selected.value.forEach(index => { if (items.value[index]) items.value[index].overrides = {} })
  editing.value = false
  persistDraft()
}
function editDestination() {
  saveEdits()
  uni.navigateTo({ url: `/pages/destination/select?scope=${scope.value}&return=photo-edit` })
}
function removeSelected() {
  if (submitting.value || choosing.value) return
  uni.showModal({ title: `移除选中的 ${selected.value.length} 张？`, content: '仅从本次选择中移除，手机相册不受影响。', success: async ({ confirm }) => {
    if (!confirm) return
    const removed = items.value.filter((_, index) => selected.value.includes(index))
    items.value = items.value.filter((_, index) => !selected.value.includes(index))
    selected.value = []
    persistDraft()
    if (!draftWarning.value) await Promise.allSettled(removed.map(item => discardCaptureOriginal(item.path, scopeOwner.value, scopeProject.value)))
  } })
}
function openWatermark() {
  if (choosing.value || submitting.value) return
  if (selected.value.length !== 1) { uni.showToast({ title: '请只勾选一张照片再保存水印', icon: 'none' }); return }
  const item = items.value[selected.value[0]]
  if (!item || scopeOwner.value !== selectionStorage.getOwner() || scopeProject.value !== String(selectionStorage.getProject().id)) return
  const values = captureOverrides(item, batchTitle.value, photographer.value)
  const assignment = values.assignment || archiveDraft.value.assignment
  try {
    setWatermarkContext(scopeOwner.value, scopeProject.value, { sourcePath: item.path, sourceQuality: 'original', sourceKind: item.source, capturedAt: item.capturedAt || '', unitProjectName: assignment?.unit_project_name || '', partName: assignment?.part_name || '', unitName: assignment?.unit_name || '', scope: scope.value, category: category.value, sitePart: [assignment?.unit_project_name, assignment?.part_name, assignment?.unit_name, assignment?.process_name, assignment?.other_node_name].filter(Boolean).join(' / '), project: project.value.name, title: values.title || assignment?.process_name || assignment?.unit_name || assignment?.other_node_name || '', photographer: values.photographer || '', photoDate: values.photo_date || '' })
    uni.navigateTo({ url: '/pages/photo/watermark' })
  } catch (reason) { uni.showToast({ title: reason instanceof Error ? reason.message : '打开水印失败', icon: 'none' }) }
}
function previewPhoto(index: number) { uni.previewImage({ current: items.value[index].path, urls: pickedPaths.value }) }
function useMyName() { photographer.value = sessionState.account?.display_name || sessionState.account?.username || '' }

const choosing = ref(false)
const pendingPaths = ref<string[]>([])
const submitting = ref(false)
const sourceInitialized = ref(false)
const permissionWarningShown = ref(false)
const uniApi = uni

const destinationLabel = computed(() => {
  const assignment = destination.value?.scope === scope.value ? destination.value.assignment : undefined
  return assignment ? fullDestinationLabel({ scope: scope.value, assignment }) : (scope.value === 'engineering' ? '选择工程部位' : '选择其它影像目录')
})
const archiveDraft = computed<UploadDraft>(() => ({
  project_id: project.value.id,
  project_name: project.value.name,
  scope: scope.value,
  category: scope.value === 'engineering' ? category.value : undefined,
  mode: mode.value,
  capture_source: source.value,
  assignment: destination.value?.scope === scope.value ? destination.value.assignment : undefined,
  requirement: scope.value === 'engineering' && category.value === 'construction' ? requirement.value || undefined : undefined,
}))
const missingArchiveInfo = computed(() => items.value.length ? items.value.flatMap(item => archiveInfoIssues({ ...archiveDraft.value, ...captureOverrides(item, batchTitle.value, photographer.value) })) : archiveInfoIssues(archiveDraft.value))
const canSubmit = computed(() => canCaptureProject(project.value) && Boolean(pickedPaths.value.length) && !choosing.value && !submitting.value)
const sourceLabel = computed(() => source.value === 'camera' ? '现场拍照' : '手机相册')
const submitLabel = computed(() => submitting.value
  ? '正在保存…'
  : pickedPaths.value.length
    ? missingArchiveInfo.value.length ? '完善归档信息' : `上传 ${pickedPaths.value.length} 张`
    : '请先选择照片')
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

function ensureCapturePermission(upload = false): boolean {
  if (!upload && project.value.id && sessionState.account) return true
  const denied = capturePermissionMessage(project.value)
  if (!denied) {
    permissionWarningShown.value = false
    return true
  }
  if (!permissionWarningShown.value) {
    permissionWarningShown.value = true
    uni.showModal({ title: denied.title, content: denied.content, showCancel: false, success: () => {
      if (!project.value.id) uni.navigateTo({ url: '/pages/project/select' })
      else uni.navigateBack()
    } })
  }
  return false
}
function chooseDestination() { uni.navigateTo({ url: `/pages/destination/select?scope=${scope.value}&return=capture` }) }

async function readOriginalCapturedAt(path: string): Promise<string> {
  try {
    const metadata = await Promise.race([readFilePrefix(path, 128 * 1024).then(parseJpegExif), new Promise<null>(resolve => setTimeout(() => resolve(null), 1200))])
    return metadata?.capturedAt || ''
  } catch { return '' }
}
async function pickMedia(nextSource: CaptureSource = source.value) {
  if (choosing.value || submitting.value || !ensureCapturePermission()) return
  const owner = scopeOwner.value
  const projectId = scopeProject.value
  if (queueRuntime.queueUsagePercent.value >= 100) {
    uni.showModal({ title: '本机同步队列已满', content: '待同步影像已经达到 160MB，请联网完成同步后再继续采集。', showCancel: false })
    return
  }
  source.value = nextSource
  choosing.value = true
  try {
    const paths = await choosePhotoPaths(nextSource)
    if (owner !== selectionStorage.getOwner() || projectId !== String(selectionStorage.getProject().id)) return
    pendingPaths.value = paths
    const captureReturnedAt = new Date().toISOString()
    const dates = paths.map(async path => (await readOriginalCapturedAt(path)) || (nextSource === 'camera' ? captureReturnedAt : ''))
    for (const [pathIndex, path] of paths.entries()) {
      if (owner !== selectionStorage.getOwner() || projectId !== String(selectionStorage.getProject().id)) break
      if (items.value.some(item => item.sourcePath === path || item.path === path)) { uni.showToast({ title: '已跳过本批重复照片', icon: 'none' }); continue }
      if (items.value.length >= 40) throw new Error('每批最多 40 张，请先上传这一批')
      const size = await getSourceFileSize(path)
      if (size > 50 * 1024 * 1024) throw new Error('单张照片不能超过 50MB')
      if (queueRuntime.queueBytes.value + items.value.reduce((sum, item) => sum + item.size, 0) + size > 160 * 1024 * 1024) throw new Error('照片总量超过 160MB，请先上传当前照片')
      const [saved, capturedAt] = await Promise.all([
        persistCaptureOriginal(path, owner, projectId),
        dates[pathIndex],
      ])
      if (owner !== selectionStorage.getOwner() || projectId !== String(selectionStorage.getProject().id)) break
      if (nextSource === 'camera' && !photographer.value) useMyName()
      items.value.push({ path: saved.originalPath, sourcePath: path, size: saved.originalSize, date: capturedAt ? localDate(new Date(capturedAt)) : '', capturedAt, source: nextSource, overrides: {} })
      pendingPaths.value = pendingPaths.value.filter(value => value !== path)
      persistDraft()
    }
  } catch (error: any) {
    if (!String(error?.errMsg || '').includes('cancel')) uni.showModal({ title: '照片选择失败', content: error instanceof Error ? error.message : '请稍后重试', showCancel: false })
  } finally {
    pendingPaths.value = []
    choosing.value = false
  }
}
async function reselectMedia() {
  const nextSource = await chooseCaptureSource()
  if (nextSource) await pickMedia(nextSource)
}
async function submitCapture() {
  if (submitting.value || choosing.value) return
  project.value = selectionStorage.getProject()
  if (!ensureCapturePermission(true)) return
  if (!project.value.id) {
    uni.showModal({ title: '还没有工程', content: '请先选择或加入工程。', showCancel: false })
    return
  }
  if (!pickedPaths.value.length) { await reselectMedia(); return }
  if (!items.value.every(item => isArchiveInfoComplete({ ...archiveDraft.value, ...captureOverrides(item, batchTitle.value, photographer.value) }))) {
    const labels = missingArchiveInfo.value.map((issue) => issue.label).join('、')
    uni.showModal({
      title: '完善归档信息',
      content: `还需选择：${labels}`,
      confirmText: '去选择',
      success: ({ confirm }) => { if (confirm) chooseDestination() },
    })
    return
  }
  if (missingDates.value) {
    selected.value = items.value.map((item, index) => !captureOverrides(item, batchTitle.value, photographer.value).photo_date ? index : -1).filter(index => index >= 0)
    editSelected()
    uni.showToast({ title: '请确认所选照片的拍摄日期', icon: 'none' })
    return
  }
  if (items.value.some(item => !captureOverrides(item, batchTitle.value, photographer.value).photographer?.trim())) {
    uni.showToast({ title: '请填写拍摄者，或点击本人', icon: 'none' }); return
  }
  const submitOwner = scopeOwner.value
  const submitProject = scopeProject.value
  const submitTitle = batchTitle.value
  const submitPhotographer = photographer.value
  submitting.value = true
  try {
    const draft: UploadDraft = { ...archiveDraft.value, assignment: captureOverrides(items.value[0], batchTitle.value, photographer.value).assignment || archiveDraft.value.assignment }
    const batch = await queueRuntime.enqueue([...pickedPaths.value], draft, items.value.map(item => captureOverrides(item, batchTitle.value, photographer.value)))
    captureDraftStorage.remember(submitOwner, submitProject, { items: [], title: submitTitle, photographer: submitPhotographer, draft })
    captureDraftStorage.clear(submitOwner, submitProject)
    if (selectionStorage.getOwner() !== submitOwner || String(selectionStorage.getProject().id) !== submitProject) return
    items.value = []
    selected.value = []
    captureDraftStorage.clear(scopeOwner.value, scopeProject.value)
    if (mode.value === 'auto') {
      uni.navigateTo({ url: `/pages/upload/confirm?batch=${batch.client_batch_id}` })
      return
    }
    uni.showToast({ title: '已加入同步队列', icon: 'success' })
    uni.switchTab({ url: '/pages/queue/index' })
  } catch (error) {
    if (selectionStorage.getOwner() !== submitOwner || String(selectionStorage.getProject().id) !== submitProject) return
    const accepted = new Set(queueRuntime.state.photos.filter(photo => photo.owner_account_id === scopeOwner.value && photo.draft.project_id === scopeProject.value).map(photo => photo.draft.capture_item_id))
    items.value = items.value.filter(item => !accepted.has(item.path))
    selected.value = []
    persistDraft()
    uni.showModal({ title: '部分影像未加入队列', content: error instanceof Error ? error.message : '处理照片失败', showCancel: false })
  } finally {
    submitting.value = false
  }
}
function changeScope(next: Scope) {
  if (scope.value === next) return
  scope.value = next
  if (destination.value?.scope !== next) destination.value = null
  items.value.forEach(item => { delete item.overrides.assignment })
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
  restoreDraft()
  source.value = query?.source === 'album' ? 'album' : 'camera'
  if (query?.autopick === '1' && !sourceInitialized.value && ensureCapturePermission()) {
    sourceInitialized.value = true
    if (!items.value.length) setTimeout(() => { void pickMedia(source.value) }, 80)
  }
})
onShow(() => {
  project.value = selectionStorage.getProject()
  applyStoredState()
  restoreDraft()
  const edited = consumePhotoEditDestination(selectionStorage.getOwner(), String(project.value.id))
  if (edited && edited.scope === scope.value) {
    selected.value.forEach(index => { if (items.value[index]) items.value[index].overrides.assignment = edited.assignment })
    persistDraft()
  }
  ensureCapturePermission()
  void refreshTree()
})
watch([() => project.value.id, scope], () => { void refreshTree() })
watch([items, batchTitle, photographer, scope, category, mode, destination], persistDraft, { deep: true })
onHide(persistDraft)
onUnload(persistDraft)
</script>

<template>
  <view class="page-shell no-tabs capture-page">
    <AppHeader :project-name="project.name" :online="queueRuntime.state.online" @select-project="uniApi.navigateTo({ url: '/pages/project/select' })" />
    <text class="page-title">采集影像</text>

    <view class="media-card card">
      <view class="media-head"><text class="media-title">{{ items.length ? `${items.length} 张照片` : '添加照片' }}</text><button class="text-button pressable" :disabled="choosing || submitting" @tap="reuseLast">沿用上一批</button></view>
      <view v-if="items.length || pendingPaths.length" class="photo-grid">
        <view v-for="(item, index) in items" :key="item.path" class="photo-tile" :class="{ selected: selected.includes(index) }">
          <image :src="item.path" mode="aspectFill" @tap="previewPhoto(index)" />
          <button class="select-photo pressable" :aria-label="`选择第 ${index + 1} 张`" @tap="togglePhoto(index)">{{ selected.includes(index) ? '✓' : index + 1 }}</button>
          <text class="photo-date" :class="{ warning: !(item.overrides.photo_date || item.date) }">{{ item.overrides.photo_date || item.date || '日期待确认' }}</text>
          <text v-if="item.overrides.assignment || item.overrides.title || item.overrides.photographer" class="photo-custom">单独设置</text>
        </view>
        <view v-for="path in pendingPaths" :key="path" class="photo-tile"><image :src="path" mode="aspectFill" /><text class="photo-date">正在保存…</text></view>
      </view>
      <text v-if="choosing" class="saving-note">正在保存照片，完成后可继续添加</text><view class="add-actions"><button class="secondary-button pressable" :disabled="choosing || submitting" @tap="pickMedia('camera')">{{ items.length ? '继续拍照' : '拍照' }}</button><button class="secondary-button pressable" :disabled="choosing || submitting" @tap="pickMedia('album')">{{ items.length ? '继续添加' : '选照片' }}</button></view>
      <view v-if="items.length" class="selection-tools"><text>{{ selectedLabel }}</text><button class="text-button pressable" @tap="selected = selected.length === items.length ? [] : items.map((_, i) => i)">{{ selected.length === items.length ? '取消全选' : '全选' }}</button></view>
      <view v-if="selected.length" class="selection-actions"><button class="secondary-button pressable" @tap="editSelected">修改 {{ selected.length }} 张</button><button class="text-button pressable" @tap="openWatermark">编辑水印</button><button class="text-button pressable" @tap="removeSelected">移除</button></view>
    </view>

    <view class="capture-settings card">
      <view class="media-head"><text class="media-title">工程部位</text><button class="text-button pressable" @tap="showAdvanced = !showAdvanced">{{ showAdvanced ? '收起' : '更多设置' }}</button></view>
      <view v-show="showAdvanced">
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
      </view>
      <button class="destination-card pressable" @tap="chooseDestination">
        <view class="destination-copy"><text class="destination-title">{{ destinationLabel }}</text><text class="destination-code">{{ destination?.scope === scope ? '更改归档位置' : scope === 'engineering' ? '选择单位、分部、单元和工序' : '选择目录' }}</text></view>
        <view class="path-arrow"><UiIcon name="chevron" :size="18" /></view>
      </button>
      <view v-if="scope === 'engineering' && currentProcesses.length" class="inline-processes"><button v-for="process in currentProcesses" :key="process" class="small-chip pressable" :class="{ chosen: destination?.assignment.process_name === process }" @tap="chooseProcess(process)">{{ process }}</button></view>
      <text v-if="mode === 'auto'" class="auto-note">归档位置先确定，上传后再辅助识别。</text>
    </view>
    <view class="metadata-card card">
      <text class="media-title">本批照片信息</text>
      <text class="field-label">题名</text><input v-model="batchTitle" class="metadata-input" maxlength="120" placeholder="留空使用当前工序名称" />
      <scroll-view scroll-x :show-scrollbar="false" class="title-scroll"><view class="title-chips"><button v-for="title in commonTitles" :key="title" class="small-chip pressable" @tap="batchTitle = title">{{ title }}</button></view></scroll-view>
      <view class="field-heading"><text class="field-label">拍摄者</text><button class="text-button pressable" @tap="useMyName">本人</button></view>
      <input v-model="photographer" class="metadata-input" maxlength="60" placeholder="填写实际拍摄者" />
      <view class="date-summary"><text>拍摄日期</text><text :class="{ warning: missingDates }">{{ missingDates ? `${missingDates} 张待确认` : '保留各自拍摄日期' }}</text></view>
      <button v-if="missingDates" class="text-button pressable" @tap="selected = items.map((item, i) => !(item.overrides.photo_date || item.date) ? i : -1).filter(i => i >= 0); editSelected()">补充缺失日期</button>
      <text v-if="draftWarning" class="warning">{{ draftWarning }}</text>
    </view>

    <view v-if="queueRuntime.queueBytes.value > 0" class="queue-status"><view class="queue-copy"><text>本机待上传</text><text>{{ formatBytes(queueRuntime.queueBytes.value) }} / 160MB</text></view><view class="usage-track"><view class="usage-fill" :style="{ transform: `scaleX(${queueRuntime.queueUsagePercent.value / 100})` }" /></view></view>
    <text v-if="!canCaptureProject(project)" class="saving-note">当前仅可查看和制作本地水印，勾选照片后点“编辑水印”。</text>
    <button v-if="canCaptureProject(project)" class="primary-button pressable submit-button" :disabled="!canSubmit" @tap="submitCapture">{{ submitLabel }}</button>
    <view v-if="editing" class="editor-mask" @tap="editing = false"><view class="editor-sheet card" @tap.stop>
      <view class="media-head"><text class="media-title">修改选中的 {{ selected.length }} 张</text><button class="text-button pressable" @tap="editing = false">取消</button></view>
      <text class="field-label">题名</text><input v-model="editor.title" class="metadata-input" maxlength="120" placeholder="留空保持原值" />
      <text class="field-label">拍摄者</text><input v-model="editor.photographer" class="metadata-input" maxlength="60" placeholder="留空保持原值" />
      <text class="field-label">拍摄日期</text><picker mode="date" :value="editor.date || localDate()" :end="localDate()" @change="editor.date = $event.detail.value"><view class="metadata-input picker-date">{{ editor.date || '选择日期（留空保持各自日期）' }}</view></picker>
      <button class="destination-card pressable" @tap="editDestination"><text>更改所选照片的工程部位</text><text>›</text></button>
      <view class="editor-actions"><button class="text-button pressable" @tap="resetSelected">恢复本批设置</button><button class="primary-button pressable" @tap="saveEdits">保存修改</button></view>
    </view></view>
    <LoadingOverlay :visible="queueRuntime.state.preparing" :message="queueRuntime.state.preparing ? (queueRuntime.state.prepareProgress.message || '正在准备影像') : `正在打开${sourceLabel}`" :progress="progressText" />
  </view>
</template>

<style scoped>
.saving-note { display:block; margin-top:12rpx; color:var(--muted); font-size:23rpx; }
.inline-processes { display:flex; flex-wrap:wrap; gap:12rpx; margin-top:18rpx; }.small-chip.chosen { color:var(--primary-strong); background:var(--primary-soft); box-shadow:inset 0 0 0 1px var(--primary-strong); }
.metadata-card { margin-top:24rpx; padding:24rpx; }
.metadata-input { width:100%; min-height:48px; box-sizing:border-box; padding:16rpx 20rpx; border:1rpx solid var(--line); border-radius:16rpx; background:var(--surface-2); color:var(--text); font-size:27rpx; }
.field-heading,.date-summary,.selection-tools,.editor-actions { display:flex; align-items:center; justify-content:space-between; gap:12rpx; }
.field-heading { margin-top:14rpx; }.field-heading .field-label { margin:0; }
.date-summary { margin-top:26rpx; color:var(--muted); font-size:24rpx; }
.text-button { margin:0; min-height:44px; padding:8rpx 12rpx; display:flex; align-items:center; justify-content:center; color:var(--primary-strong); font-size:24rpx; background:transparent; line-height:1.4; }
.title-scroll :deep(::-webkit-scrollbar) { display:none; width:0; height:0; }
.title-scroll { margin-top:12rpx; white-space:nowrap; }.title-chips { display:inline-flex; gap:12rpx; }.small-chip { flex:none; min-height:40px; padding:10rpx 20rpx; border-radius:12rpx; background:var(--surface-2); color:var(--muted); font-size:23rpx; line-height:1.5; display:flex; align-items:center; }
.photo-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12rpx; margin-top:18rpx; }.photo-tile { position:relative; min-width:0; border:2px solid transparent; border-radius:16rpx; overflow:hidden; background:var(--surface-2); }.photo-tile.selected { border-color:var(--primary-strong); }.photo-tile image { width:100%; height:172rpx; display:block; }.select-photo { position:absolute; top:4rpx; right:4rpx; min-width:44px; min-height:44px; padding:0; background:rgba(0,0,0,.55); color:white; line-height:44px; font-size:24rpx; border-radius:50%; }.selected .select-photo { background:var(--primary-strong); color:var(--surface); }.photo-date { display:block; text-align:center; font-size:20rpx; padding:10rpx 0; color:var(--muted); }.photo-custom { position:absolute; bottom:48rpx; left:0; background:rgba(0,0,0,.6); color:white; padding:4rpx 8rpx; font-size:19rpx; }.warning { color:var(--warning); }
.add-actions { display:grid; grid-template-columns:1fr 1fr; gap:14rpx; margin-top:22rpx; }.add-actions button,.selection-actions button { font-size:25rpx; min-height:44px; }.selection-tools { font-size:22rpx; color:var(--muted); margin-top:12rpx; }.selection-actions { display:flex; flex-wrap:wrap; gap:20rpx; align-items:center; }
.editor-mask { position:fixed; inset:0; z-index:60; background:rgba(0,0,0,.55); display:flex; align-items:flex-end; }.editor-sheet { width:100%; max-height:85vh; overflow-y:auto; padding:28rpx 28rpx calc(30rpx + env(safe-area-inset-bottom)); border-radius:28rpx 28rpx 0 0; }.editor-actions { margin-top:24rpx; }.editor-actions .primary-button { flex:1; min-height:48px; font-size:26rpx; }.picker-date { display:flex; align-items:center; }

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
.destination-title { display: block; overflow: hidden; color: var(--text); font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: normal; line-height:1.5; }
.destination-code { display: block; margin-top: 5rpx; color: var(--primary-strong); font-size: 20rpx; }
.path-arrow { display: grid; flex: 0 0 auto; place-items: center; width: 36rpx; height: 52rpx; margin-left: 16rpx; color: var(--muted); }
.archive-summary { overflow: hidden; margin-top: 12rpx; border: 1rpx solid var(--line); border-radius: 18rpx; background: rgba(255, 255, 255, 0.015); }
.archive-row { display: grid; grid-template-columns: 126rpx minmax(0, 1fr); gap: 18rpx; padding: 15rpx 18rpx; border-bottom: 1rpx solid var(--line); font-size: 22rpx; line-height: 1.45; }
.archive-row:last-child { border-bottom: 0; }
.archive-row > text:first-child { color: var(--muted); }
.archive-row > text:last-child { overflow: hidden; color: var(--text); text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.archive-row.missing > text:last-child { color: var(--warning); }
.auto-note { display: block; margin-top: 12rpx; color: var(--muted); font-size: 21rpx; }
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
