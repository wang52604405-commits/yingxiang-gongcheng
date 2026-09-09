<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { onLoad, onReady, onShow, onUnload } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { selectionStorage } from '@/stores/selection'
import { sessionState } from '@/services/auth'
import { consumeWatermarkContext, watermarkContextMatches, watermarkUploadDraft, type WatermarkContext } from '@/services/watermark-context'
import { generatePhotoWatermark, getCurrentWatermarkLocation, saveWatermarkToAlbum } from '@/services/photo-watermark'
import { COMPANY_LOGOS } from '@/services/company-logos'
import { queueRuntime } from '@/services/queue-runtime'
import { capturePermissionMessage } from '@/services/project-membership'
import { mobileApi } from '@/api/mobile'
import type { ProjectSummary } from '@/types/domain'

const context = ref<WatermarkContext | null>(null)
const activeProject = ref(selectionStorage.getProject())
const form = reactive({ project: '', title: '', photographer: '', photoDate: '', sitePart: '', locationText: '', unitProjectName: '', partName: '', unitName: '', constructionContent: '', capturedAt: '', contractor: '' })
const locationLabel = ref<'当前定位' | '手填位置'>('手填位置')
const logoIndex = ref(0)
const logoNames = ['不加企业标志', ...COMPANY_LOGOS.map((item) => item.name)]
const largeExport = ref(false)
const rendering = ref(false)
const saving = ref(false)
const locating = ref(false)
const uploading = ref(false)
const uploadedBatchId = ref('')
const busy = computed(() => rendering.value || saving.value || locating.value || uploading.value)
const error = ref('')
const showSettings = ref(false)
const preview = ref<{ tempFilePath: string; width: number; height: number } | null>(null)
const dirty = ref(true)
let alive = true
let choosingHierarchy = false
const photographerVerified = computed(() => activeProject.value.photographer_verified === true && Boolean(activeProject.value.photographer_name))
const timeText = computed(() => {
  if (!form.capturedAt) return form.photoDate || '未取得原始拍摄时间'
  const value = new Date(form.capturedAt)
  if (!Number.isFinite(value.getTime())) return form.photoDate || '未取得原始拍摄时间'
  return value.toLocaleString('zh-CN', { hour12: false })
})
function preferenceKey() { return context.value ? `engineering-image:watermark-template:v1:${context.value.owner}:${context.value.projectId}` : '' }
function chooseHierarchy() { if (!busy.value && sameContext()) { choosingHierarchy = true; uni.navigateTo({ url: '/pages/destination/select?scope=engineering&return=capture' }) } }
async function refreshIdentity() {
  if (!context.value) return
  try {
    const response = await mobileApi.projects()
    if (!alive || !sameContext()) return
    const project = response.projects.find((item: ProjectSummary) => String(item.id) === context.value?.projectId)
    if (!project) throw new Error('当前账号已无此项目权限')
    activeProject.value = project
    selectionStorage.setProject(project)
    form.project = project.name
    form.photographer = project.photographer_name || ''
  } catch (reason) { if (!photographerVerified.value) showError(reason) }
}

const previewOnly = computed(() => context.value?.sourceQuality === 'preview')
const saveLabel = computed(() => saving.value ? '正在保存…' : previewOnly.value ? '保存水印预览到相册' : '保存水印照片到相册')
const previewImage = computed(() => preview.value?.tempFilePath || context.value?.sourcePath || '')
function sameContext(): boolean {
  return Boolean(context.value && watermarkContextMatches(context.value, selectionStorage.getOwner(), String(selectionStorage.getProject().id || '')) && String(sessionState.account?.id || '') === context.value.owner)
}
function requireContext(): WatermarkContext {
  if (!alive || !sameContext() || !context.value) throw new Error('账号或工程已切换，请返回重新选择照片')
  return context.value
}
function showError(reason: unknown) {
  error.value = reason instanceof Error ? reason.message : '操作失败，请重试'
  showSettings.value = Boolean((reason as { canOpenSettings?: boolean })?.canOpenSettings)
}
async function renderLatest() {
  const source = requireContext()
  if (!photographerVerified.value) throw new Error('拍摄者姓名尚未认证，请联系项目负责人审核')
  const result = await generatePhotoWatermark(source.sourcePath, {
    companyName: COMPANY_LOGOS[logoIndex.value - 1]?.name || '', project: form.project, unitProjectName: form.unitProjectName, partName: form.partName, unitName: form.unitName,
    constructionContent: form.constructionContent, capturedAt: form.capturedAt || form.photoDate,
    photographer: form.photographer, contractor: form.contractor,
    location: form.locationText.trim() ? { label: locationLabel.value, text: form.locationText.trim() } : undefined,
  }, {
    maxEdge: largeExport.value ? 4096 : 2048,
    logoPath: logoIndex.value ? COMPANY_LOGOS[logoIndex.value - 1]?.path : undefined,
    logoCrop: logoIndex.value ? COMPANY_LOGOS[logoIndex.value - 1]?.symbolCrop : undefined,
  })
  requireContext()
  preview.value = result
  dirty.value = false
  return result
}
async function updatePreview() {
  if (busy.value || !context.value) return
  rendering.value = true
  error.value = ''
  showSettings.value = false
  try { await renderLatest() } catch (reason) { if (alive) showError(reason) }
  finally { rendering.value = false }
}
async function savePhoto() {
  if (busy.value) return
  saving.value = true
  error.value = ''
  showSettings.value = false
  try {
    requireContext()
    const output = dirty.value || !preview.value ? await renderLatest() : preview.value
    requireContext()
    await saveWatermarkToAlbum(output.tempFilePath)
    if (alive && sameContext()) uni.showToast({ title: '水印副本已保存到相册', icon: 'success' })
  } catch (reason) { if (alive) showError(reason) }
  finally { saving.value = false }
}
async function uploadAuto() {
  if (busy.value || uploadedBatchId.value) return
  uploading.value = true
  error.value = ''
  showSettings.value = false
  let captureId = ''
  try {
    const source = requireContext()
    const project = selectionStorage.getProject()
    const denied = capturePermissionMessage(project)
    if (denied) throw new Error(denied.content)
    if (!photographerVerified.value) throw new Error('拍摄者姓名尚未认证，请联系项目负责人审核')
    const output = dirty.value || !preview.value ? await renderLatest() : preview.value
    requireContext()
    captureId = `watermark:${output.tempFilePath}`
    const title = [form.unitName, form.constructionContent.trim()].filter(Boolean).join('—')
    const sitePart = [form.unitProjectName, form.partName, form.unitName, form.constructionContent.trim()].filter(Boolean).join(' / ')
    const draft = watermarkUploadDraft(source, { ...form, title, sitePart }, project.name, captureId)
    const batch = await queueRuntime.enqueue([output.tempFilePath], draft)
    uploadedBatchId.value = batch.client_batch_id
    if (alive && sameContext()) uni.showToast({ title: '已加入上传归类队列', icon: 'success' })
  } catch (reason) {
    const accepted = captureId && queueRuntime.state.photos.find((photo) => photo.owner_account_id === context.value?.owner && photo.draft.project_id === context.value?.projectId && photo.draft.capture_item_id === captureId)
    if (accepted) uploadedBatchId.value = accepted.client_batch_id
    if (alive) showError(reason)
  } finally { uploading.value = false }
}
function openQueue() { uni.switchTab({ url: '/pages/queue/index' }) }
async function getLocation() {
  if (busy.value) return
  locating.value = true
  error.value = ''
  showSettings.value = false
  try {
    requireContext()
    const location = await getCurrentWatermarkLocation()
    requireContext()
    form.locationText = location.text
    locationLabel.value = '当前定位'
  } catch (reason) { if (alive) showError(reason) }
  finally { locating.value = false }
}
function clearLocation() { form.locationText = ''; locationLabel.value = '手填位置' }
function previewLarge() { if (previewImage.value) uni.previewImage({ current: previewImage.value, urls: [previewImage.value] }) }
function openSettings() { uni.openSetting({}) }
function changeExportQuality(event: any) { largeExport.value = Boolean(event?.detail?.value) }
onLoad(() => {
  const value = consumeWatermarkContext(selectionStorage.getOwner(), String(selectionStorage.getProject().id || ''))
  if (!value || String(sessionState.account?.id || '') !== value.owner) { error.value = '照片已失效，请返回重新选择'; return }
  context.value = value
  Object.assign(form, { project: activeProject.value.name, constructionContent: value.title === value.unitName ? '' : value.title,
    photographer: activeProject.value.photographer_name || '', photoDate: value.photoDate, capturedAt: value.capturedAt || '',
    unitProjectName: value.unitProjectName || '', partName: value.partName || '', unitName: value.unitName || '' })
  const pref = uni.getStorageSync(preferenceKey()) || {}
  logoIndex.value = Math.max(0, COMPANY_LOGOS.findIndex(item => item.id === pref.logoId) + 1)
  form.contractor = String(pref.contractor || '').slice(0, 100)

})
onReady(async () => { await refreshIdentity(); await updatePreview() })
onShow(() => {
  activeProject.value = selectionStorage.getProject()
  if (choosingHierarchy && context.value && sameContext()) {
    choosingHierarchy = false
    const assignment = selectionStorage.getDestination()?.assignment
    form.unitProjectName = assignment?.unit_project_name || ''
    form.partName = assignment?.part_name || ''
    form.unitName = assignment?.unit_name || ''
  }
  if (context.value && !sameContext()) { context.value = null; preview.value = null; form.locationText = ''; error.value = '账号或工程已切换，请返回重新选择照片' }
})
onUnload(() => { alive = false; form.locationText = '' })
watch([form, locationLabel, logoIndex, largeExport], () => { dirty.value = true; uploadedBatchId.value = '' }, { deep: true })
watch([logoIndex, () => form.contractor], () => { if (context.value && sameContext()) uni.setStorageSync(preferenceKey(), { logoId: COMPANY_LOGOS[logoIndex.value - 1]?.id || '', contractor: form.contractor }) })
</script>

<template>
  <view class="page-shell no-tabs watermark-page">
    <PageHeader :title="previewOnly ? '水印预览图' : '水印照片'" />
    <template v-if="context">
      <button class="watermark-preview pressable" @tap="previewLarge"><image :src="previewImage" mode="aspectFit" /><text v-if="rendering" class="preview-badge">正在生成预览…</text><text v-else-if="dirty && preview" class="preview-badge">设置已更改，请更新预览</text></button>
      <view class="preview-caption"><text>{{ preview ? `${preview.width} × ${preview.height}` : '原始画面' }}</text><button class="text-button pressable" :disabled="busy" @tap="updatePreview">更新预览</button></view>
      <text v-if="previewOnly" class="quality-note">当前使用预览图，保存和上传的清晰度均受预览图限制。</text>
      <text class="copy-note">生成带水印的副本，原照片保持不变。</text>
      <text class="archive-target">归档项目：{{ activeProject.name }}</text>
      <view class="edit-card card">
        <text class="section-title">固定工程水印</text>
        <text class="copy-note">左下角 · 浅蓝色块80%透明 · 紧凑水印 · 约占画面1/10</text>
        <text class="field-label">企业标志</text><picker :range="logoNames" :value="logoIndex" :disabled="busy" @change="logoIndex = Number($event.detail.value)"><view class="input date-input">{{ logoNames[logoIndex] }}</view></picker>
        <text class="field-label">项目名称</text><view class="readonly-value">{{ form.project }}</view>
        <view class="field-heading"><text class="field-label">项目划分</text><button class="text-button pressable" :disabled="busy" @tap="chooseHierarchy">选择工程部位</button></view>
        <view class="hierarchy-row"><text>单位工程</text><text>{{ form.unitProjectName || '未选择' }}</text></view>
        <view class="hierarchy-row"><text>施工区域</text><text>{{ form.partName || '未选择分部工程' }}</text></view>
        <view class="hierarchy-row"><text>单元工程</text><text>{{ form.unitName || '未选择，可由后台识别' }}</text></view>
        <text class="field-label">具体施工内容</text><input v-model="form.constructionContent" class="input" maxlength="60" placeholder="填写在单元工程名称后，如钢筋绑扎检查" :disabled="busy" />
        <text class="field-label">时间（自动）</text><view class="readonly-value">{{ timeText }}</view>
        <text class="field-label">拍摄者</text><view class="readonly-value">{{ photographerVerified ? form.photographer + ' · 已认证' : '待项目负责人认证' }}</view>
        <view class="field-heading"><text class="field-label">位置</text><button v-if="form.locationText" class="text-button pressable" :disabled="busy" @tap="clearLocation">清除</button></view>
        <input v-model="form.locationText" class="input" maxlength="120" placeholder="定位或手填地址" :disabled="busy" @input="locationLabel = '手填位置'" />
        <view class="location-actions"><text v-if="form.locationText" class="location-source">{{ locationLabel }}</text><button class="text-button pressable" :disabled="busy" @tap="getLocation">{{ locating ? '正在获取…' : '获取当前位置' }}</button></view>
        <text v-if="locationLabel === '当前定位' && form.locationText" class="copy-note">当前位置是此刻手机的位置，不代表旧照片的拍摄地点。</text>
        <text class="field-label">施工单位名称（底部色块）</text><input v-model="form.contractor" class="input" maxlength="100" placeholder="手填施工单位全称" :disabled="busy" />
        <view class="export-row"><text>高清导出</text><switch :checked="largeExport" :disabled="busy || previewOnly" @change="changeExportQuality" /></view>
      </view>
    </template>
    <view v-if="error" class="error-card" role="alert"><text>{{ error }}</text><button v-if="showSettings" class="text-button pressable" @tap="openSettings">打开权限设置</button></view>
    <template v-if="context">
      <text class="classify-note">上传后自动归类到施工单元；识别不到的照片送电脑端待分类，供人工筛选。</text>
      <button class="primary-button pressable save-button" :disabled="busy || Boolean(uploadedBatchId)" @tap="uploadAuto">{{ uploading ? '正在准备上传…' : uploadedBatchId ? '已加入上传归类队列' : previewOnly ? '上传水印预览并归类' : '上传并自动归类' }}</button>
      <button class="secondary-button pressable album-button" :disabled="busy" @tap="savePhoto">{{ saveLabel }}</button>
      <button v-if="uploadedBatchId" class="text-button queue-link pressable" @tap="openQueue">查看同步记录</button>
    </template>
  </view>
</template>

<style scoped>
.readonly-value { color:var(--text); font-size:26rpx; line-height:1.5; padding:14rpx 0; }.hierarchy-row { display:grid; grid-template-columns:130rpx 1fr; gap:12rpx; padding:15rpx 0; border-bottom:1rpx solid var(--line); font-size:24rpx; line-height:1.5; }.hierarchy-row text:first-child { color:var(--muted); }
.watermark-page { padding-bottom:calc(48rpx + var(--safe-bottom)); }
.watermark-preview { position:relative; display:grid; place-items:center; width:100%; height:500rpx; padding:0; overflow:hidden; border-radius:24rpx; background:#071215; }
.watermark-preview image { width:100%; height:100%; }
.preview-badge { position:absolute; bottom:16rpx; left:16rpx; right:16rpx; padding:10rpx; border-radius:10rpx; color:white; background:rgba(0,0,0,.65); font-size:22rpx; }
.preview-caption,.field-heading,.location-actions,.export-row { display:flex; align-items:center; justify-content:space-between; gap:16rpx; color:var(--muted); font-size:23rpx; }
.field-heading { margin-top:18rpx; }.field-heading .field-label { margin:0; }
.copy-note,.quality-note { display:block; color:var(--muted); font-size:23rpx; line-height:1.6; }.quality-note { color:var(--warning); margin-bottom:10rpx; }
.edit-card { margin-top:24rpx; padding:24rpx; }.section-title { font-size:28rpx; font-weight:650; color:var(--text); }
.input { box-sizing:border-box; min-height:48px; }.date-input { display:flex; align-items:center; }
.text-button { display:inline-flex; align-items:center; justify-content:center; min-height:44px; padding:0 10rpx; color:var(--primary-strong); background:transparent; font-size:24rpx; line-height:1.4; }
.location-actions { justify-content:flex-end; }.location-source { margin-right:auto; font-size:22rpx; color:var(--muted); }
.advanced-toggle { width:100%; display:flex; justify-content:space-between; align-items:center; min-height:44px; padding:0; background:transparent; color:var(--text); font-size:27rpx; }.advanced-toggle text:last-child { color:var(--primary-strong); font-size:24rpx; }
.option-row { display:flex; flex-wrap:wrap; gap:12rpx; }.option-chip { display:inline-flex; align-items:center; min-height:44px; padding:0 22rpx; background:var(--surface-2); border:1rpx solid var(--line); color:var(--muted); font-size:24rpx; border-radius:16rpx; }.option-chip.active { background:var(--primary-soft); color:var(--primary-strong); border-color:var(--primary-strong); }
.export-row { margin-top:24rpx; }.error-card { margin-top:24rpx; padding:20rpx; border-radius:18rpx; color:var(--danger); background:var(--surface-2); font-size:24rpx; line-height:1.5; }.save-button { margin-top:28rpx; }
.archive-target { display:block; margin-top:18rpx; color:var(--primary-strong); font-size:25rpx; line-height:1.5; }.classify-note { display:block; margin-top:26rpx; color:var(--muted); font-size:23rpx; line-height:1.6; }.album-button { width:100%; min-height:48px; margin-top:16rpx; font-size:26rpx; }.queue-link { display:flex; margin-top:14rpx; }
</style>
