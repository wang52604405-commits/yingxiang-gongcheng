<script setup lang="ts">
import { beginWatermarkDivision, consumeWatermarkDivision, watermarkDivisionFields } from '@/services/watermark-division'
import { computed, reactive, ref, watch } from 'vue'
import { onLoad, onReady, onShow, onHide, onResize, onUnload } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { selectionStorage } from '@/stores/selection'
import { sessionState } from '@/services/auth'
import { consumeWatermarkContext, watermarkContextMatches, watermarkUploadDraft, type WatermarkContext } from '@/services/watermark-context'
import { generatePhotoWatermark, getCurrentWatermarkLocation, saveWatermarkToAlbum } from '@/services/photo-watermark'
import { COMPANY_LOGOS } from '@/services/company-logos'
import { queueRuntime } from '@/services/queue-runtime'
import { canCaptureProject, capturePermissionMessage } from '@/services/project-membership'
import { mobileApi } from '@/api/mobile'
import type { ProjectSummary } from '@/types/domain'

const cameraMode = ref(false)
const shotTaken = ref(false)
const editingCamera = ref(false)
const cameraReady = ref(false)
const cameraActive = ref(true)
const shooting = ref(false)
const cameraPosition = ref<'back' | 'front'>('back')
const cameraFlash = ref<'off' | 'auto'>('off')
const cameraWidth = ref(343)
const cameraHeight = ref(457)
const liveCamera = computed(() => cameraMode.value && !shotTaken.value)
let overlayTimer: ReturnType<typeof setTimeout> | undefined
let clockTimer: ReturnType<typeof setInterval> | undefined
const context = ref<WatermarkContext | null>(null)
const activeProject = ref(selectionStorage.getProject())
const form = reactive({ project: '', title: '', photographer: '', photoDate: '', sitePart: '', locationText: '', unitProjectName: '', partName: '', unitName: '', unitCode: '', constructionContent: '', capturedAt: '', contractor: '' })
const locationLabel = ref<'当前定位' | '手填位置'>('手填位置')
const manualLocation = ref(false)
const manualDate = ref('')
const manualTime = ref('')
const manualPhoto = computed(() => context.value?.sourceKind !== 'camera')
const logoIndex = ref(0)
const logoNames = ['不加企业标志', ...COMPANY_LOGOS.map((item) => item.name)]
const largeExport = ref(false)
const rendering = ref(false)
const saving = ref(false)
const locating = ref(false)
const uploading = ref(false)
const uploadedBatchId = ref('')
const busy = computed(() => shooting.value || rendering.value || saving.value || locating.value || uploading.value)
const error = ref('')
const showSettings = ref(false)
const preview = ref<{ tempFilePath: string; width: number; height: number } | null>(null)
const dirty = ref(true)
let alive = true
let choosingHierarchy = false
const divisionKeyword = ref('')
const photographerVerified = computed(() => activeProject.value.photographer_verified === true && Boolean(activeProject.value.photographer_name))
const timeText = computed(() => {
  if (!form.capturedAt) return form.photoDate || '未取得原始拍摄时间'
  const value = new Date(form.capturedAt)
  if (!Number.isFinite(value.getTime())) return form.photoDate || '未取得原始拍摄时间'
  return value.toLocaleString('zh-CN', { hour12: false })
})
function preferenceKey() { return context.value ? `engineering-image:watermark-template:v1:${context.value.owner}:${context.value.projectId}` : '' }
function chooseHierarchy() { if (!busy.value && sameContext()) { beginWatermarkDivision(selectionStorage.getOwner(), String(activeProject.value.id)); choosingHierarchy = true; uni.navigateTo({ url: '/pages/destination/select?scope=engineering&return=watermark&keyword=' + encodeURIComponent(divisionKeyword.value.trim()) }) } }
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
  if (manualPhoto.value && (!manualDate.value || !manualTime.value || !form.locationText.trim())) throw new Error('请手动填写这张照片的时间和地点')
  const result = await generatePhotoWatermark(source.sourcePath, {
    companyName: COMPANY_LOGOS[logoIndex.value - 1]?.name || '', project: form.project, unitProjectName: form.unitProjectName, partName: form.partName, unitName: form.unitName,
    constructionContent: form.constructionContent, capturedAt: form.capturedAt || form.photoDate,
    photographer: form.photographer, contractor: form.contractor,
    location: form.locationText.trim() ? { label: locationLabel.value, text: form.locationText.trim() } : undefined,
  }, {
    maxEdge: largeExport.value ? 4096 : 2048,
    overlaySize: liveCamera.value ? { width: Math.round(cameraWidth.value * 3), height: Math.round(cameraHeight.value * 3) } : undefined,
    logoPath: logoIndex.value ? COMPANY_LOGOS[logoIndex.value - 1]?.path : undefined,
    logoCrop: logoIndex.value ? COMPANY_LOGOS[logoIndex.value - 1]?.symbolCrop : undefined,
  })
  requireContext()
  const oldOverlay = liveCamera.value ? preview.value?.tempFilePath : ''
  preview.value = result
  if (oldOverlay && oldOverlay !== result.tempFilePath) { try { (globalThis as any).wx?.getFileSystemManager().unlink({ filePath: oldOverlay, fail() {} }) } catch {} }
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
  if (busy.value || liveCamera.value) return
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
  if (busy.value || liveCamera.value || uploadedBatchId.value) return
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
    const sitePart = [form.unitCode, form.unitProjectName, form.partName, form.unitName, form.constructionContent.trim()].filter(Boolean).join(' / ')
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
    manualLocation.value = false
  } catch (reason) { if (alive) { manualLocation.value = true; showError(reason) } }
  finally { locating.value = false }
}
function clearLocation() { form.locationText = ''; locationLabel.value = '手填位置' }
function previewLarge() { if (previewImage.value) uni.previewImage({ current: previewImage.value, urls: [previewImage.value] }) }
function openSettings() { uni.openSetting({}) }
function changeExportQuality(event: any) { largeExport.value = Boolean(event?.detail?.value) }
onLoad((query) => {
  cameraMode.value = query?.camera === '1'
  resizeCamera()
  const value: WatermarkContext | null = cameraMode.value ? { owner: selectionStorage.getOwner(), projectId: String(activeProject.value.id || ''), sourcePath: 'camera-pending', sourceQuality: 'original', sourceKind: 'camera', project: activeProject.value.name, title: '', photographer: '', photoDate: '', capturedAt: new Date().toISOString(), scope: selectionStorage.getUploadPreset()?.scope || 'engineering', category: selectionStorage.getUploadPreset()?.category || 'construction' } : consumeWatermarkContext(selectionStorage.getOwner(), String(selectionStorage.getProject().id || ''))
  if (!value || String(sessionState.account?.id || '') !== value.owner) { error.value = '照片已失效，请返回重新选择'; return }
  context.value = value
  Object.assign(form, { project: activeProject.value.name, constructionContent: value.title === value.unitName ? '' : value.title,
    photographer: activeProject.value.photographer_name || '', photoDate: value.photoDate, capturedAt: value.capturedAt || '',
    unitProjectName: value.unitProjectName || '', partName: value.partName || '', unitName: value.unitName || '' })
  if (value.sourceKind !== 'camera') { form.photoDate = ''; form.capturedAt = ''; manualLocation.value = true }
  const pref = uni.getStorageSync(preferenceKey()) || {}
  logoIndex.value = Math.max(0, COMPANY_LOGOS.findIndex(item => item.id === pref.logoId) + 1)
  form.contractor = String(pref.contractor || '').slice(0, 100)

})
onReady(async () => { await refreshIdentity(); if (!manualPhoto.value) await updatePreview(); if (context.value?.sourceKind === 'camera' && sameContext() && photographerVerified.value && queueRuntime.state.foreground) { await getLocation(); if (liveCamera.value) await updatePreview() } })
onShow(() => {
  cameraActive.value = true
  activeProject.value = selectionStorage.getProject()
  if (choosingHierarchy && context.value && sameContext()) {
    choosingHierarchy = false
    const selected = consumeWatermarkDivision(selectionStorage.getOwner(), String(activeProject.value.id))
    if (selected) Object.assign(form, watermarkDivisionFields(selected.assignment))
  }
  if (liveCamera.value) scheduleOverlay()
  if (context.value && !sameContext()) { context.value = null; preview.value = null; form.locationText = ''; error.value = '账号或工程已切换，请返回重新选择照片' }
})
onHide(() => { cameraActive.value = false; cameraReady.value = false; clearTimeout(overlayTimer) })
onResize(resizeCamera)
onUnload(() => { alive = false; form.locationText = ''; clearTimeout(overlayTimer); clearInterval(clockTimer) })
watch([form, locationLabel, logoIndex, largeExport], () => { dirty.value = true; uploadedBatchId.value = ''; scheduleOverlay() }, { deep: true })
watch([manualDate, manualTime], () => { if (manualPhoto.value) { form.photoDate = manualDate.value; form.capturedAt = manualDate.value && manualTime.value ? manualDate.value + 'T' + manualTime.value + ':00' : '' } })
watch([logoIndex, () => form.contractor], () => { if (context.value && sameContext()) uni.setStorageSync(preferenceKey(), { logoId: COMPANY_LOGOS[logoIndex.value - 1]?.id || '', contractor: form.contractor }) })

function resizeCamera() {
  const size = uni.getSystemInfoSync()
  const landscape = size.windowWidth > size.windowHeight
  cameraWidth.value = landscape ? Math.max(180, Math.min(size.windowWidth - 32, (size.windowHeight - 170) * 4 / 3)) : Math.min(size.windowWidth - 32, Math.max(180, (size.windowHeight - 230) * 3 / 4))
  cameraHeight.value = cameraWidth.value * (landscape ? 3 / 4 : 4 / 3)
  scheduleOverlay()
}
function scheduleOverlay() {
  clearTimeout(overlayTimer)
  if (!alive || !liveCamera.value || !cameraActive.value || editingCamera.value) return
  overlayTimer = setTimeout(() => { if (busy.value) scheduleOverlay(); else void updatePreview() }, 350)
}
function editCameraWatermark() { editingCamera.value = true; cameraReady.value = false; clearTimeout(overlayTimer) }
function returnToCamera() { editingCamera.value = false; form.capturedAt = new Date().toISOString(); scheduleOverlay(); uni.pageScrollTo({ scrollTop: 0, duration: 0 }) }
function onCameraError(event: any) { cameraReady.value = false; error.value = event?.detail?.errMsg || '相机未能打开，请允许相机权限后重试'; showSettings.value = true }
async function takeWatermarkPhoto() {
  if (busy.value || !cameraReady.value || !photographerVerified.value) return
  shooting.value = true; error.value = ''; clearTimeout(overlayTimer)
  try {
    requireContext()
    const capturedAt = new Date().toISOString()
    const result = await new Promise<any>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('拍照超时，请重试')), 20000)
      uni.createCameraContext().takePhoto({ quality: 'high', success: result => { clearTimeout(timer); resolve(result) }, fail: reason => { clearTimeout(timer); reject(new Error(reason.errMsg || '拍照失败，请重试')) } })
    })
    requireContext()
    if (!result.tempImagePath) throw new Error('未取得照片，请重新拍摄')
    context.value!.sourcePath = result.tempImagePath
    context.value!.capturedAt = capturedAt
    form.capturedAt = capturedAt
    form.photoDate = new Date(capturedAt).toLocaleDateString('sv-SE')
    shotTaken.value = true; preview.value = null; dirty.value = true
    await renderLatest()
  } catch (reason) { if (alive) showError(reason) }
  finally { shooting.value = false }
}
function continueCamera() {
  if (busy.value) return
  shotTaken.value = false; cameraReady.value = false; preview.value = null; uploadedBatchId.value = ''; dirty.value = true
  context.value!.sourcePath = 'camera-pending'; form.capturedAt = new Date().toISOString(); scheduleOverlay()
}
onReady(() => { if (cameraMode.value) clockTimer = setInterval(() => { if (liveCamera.value && cameraActive.value && !busy.value) form.capturedAt = new Date().toISOString() }, 15000) })

</script>

<template>
  <view class="page-shell no-tabs watermark-page">
    <PageHeader :title="liveCamera ? '水印相机' : previewOnly ? '水印预览图' : '水印照片'" />
    <template v-if="context">
      <template v-if="liveCamera">
        <view v-if="!editingCamera" class="camera-stage" :style="{ width: cameraWidth + 'px', height: cameraHeight + 'px' }">
          <camera v-if="cameraActive" id="watermark-camera" class="live-camera" mode="normal" resolution="high" :device-position="cameraPosition" :flash="cameraFlash" @initdone="cameraReady = true" @error="onCameraError" @stop="cameraReady = false">
            <cover-image v-if="preview" class="camera-overlay" :src="preview.tempFilePath" @tap="editCameraWatermark" />
          </camera>
        </view>
        <view v-if="!editingCamera" class="camera-tools"><button class="secondary-button" :disabled="busy" @tap="cameraPosition = cameraPosition === 'back' ? 'front' : 'back'">翻转</button><button class="primary-button camera-edit" :disabled="busy" @tap="editCameraWatermark">编辑水印</button><button class="secondary-button" :disabled="busy" @tap="cameraFlash = cameraFlash === 'off' ? 'auto' : 'off'">{{ cameraFlash === 'off' ? '闪光关' : '闪光自动' }}</button></view>
        <button v-if="!editingCamera" class="primary-button camera-shutter" :disabled="busy || !cameraReady || !photographerVerified" @tap="takeWatermarkPhoto">{{ shooting ? '正在拍摄…' : '拍照' }}</button>
        <button v-else class="primary-button" :disabled="busy" @tap="returnToCamera">完成编辑 · 返回拍摄</button>
      </template>
      <button v-if="!liveCamera" class="watermark-preview pressable" @tap="previewLarge"><image :src="previewImage" mode="aspectFit" /><text v-if="rendering" class="preview-badge">正在生成预览…</text><text v-else-if="dirty && preview" class="preview-badge">设置已更改，请更新预览</text></button>
      <view v-if="!liveCamera" class="preview-caption"><text>{{ preview ? `${preview.width} × ${preview.height}` : '原始画面' }}</text><button class="text-button pressable" :disabled="busy" @tap="updatePreview">更新预览</button></view>
      <text v-if="previewOnly" class="quality-note">当前使用预览图，保存和上传的清晰度均受预览图限制。</text>
      <text v-if="!liveCamera" class="copy-note">生成带水印的副本，原照片保持不变。</text>
      <text class="archive-target">归档项目：{{ activeProject.name }}</text>
      <view v-if="!liveCamera || editingCamera" class="edit-card card">
        <text class="section-title">固定工程水印</text>
        <text class="copy-note">左下角 · 浅蓝色块80%透明 · 紧凑水印 · 约占画面1/8</text>
        <text class="field-label">企业标志</text><picker :range="logoNames" :value="logoIndex" :disabled="busy" @change="logoIndex = Number($event.detail.value)"><view class="input date-input">{{ logoNames[logoIndex] }}</view></picker>
        <text class="field-label">项目名称</text><view class="readonly-value">{{ form.project }}</view>
        <text class="field-label">搜索项目划分</text><view class="division-search"><input v-model="divisionKeyword" class="input" maxlength="80" placeholder="如：底板、单元编码，可用空格组合关键词" confirm-type="search" :disabled="busy" @confirm="chooseHierarchy" /><button class="text-button pressable" :disabled="busy" @tap="chooseHierarchy">搜索选择</button></view>
        <view class="hierarchy-row"><text>单位工程</text><text>{{ form.unitProjectName || '未选择' }}</text></view>
        <view class="hierarchy-row"><text>施工区域</text><text>{{ form.partName || '未选择分部工程' }}</text></view>
        <view class="hierarchy-row"><text>施工内容前缀</text><text>{{ form.unitName || '未选择，可由后台识别' }}</text></view>
        <text class="field-label">具体施工内容</text><input v-model="form.constructionContent" class="input" maxlength="60" placeholder="仅填写后面的内容，如钢筋绑扎检查" :disabled="busy" />
        <text class="field-label">{{ manualPhoto ? '时间（相册照片需手填）' : '时间（自动）' }}</text>
        <view v-if="manualPhoto" class="manual-datetime"><picker mode="date" :value="manualDate" :disabled="busy" @change="manualDate = $event.detail.value"><view class="input date-input">{{ manualDate || '选择拍摄日期' }}</view></picker><picker mode="time" :value="manualTime" :disabled="busy" @change="manualTime = $event.detail.value"><view class="input date-input">{{ manualTime || '选择拍摄时间' }}</view></picker></view>
        <view v-else class="readonly-value">{{ timeText }}</view>
        <text class="field-label">拍摄者</text><view class="readonly-value">{{ photographerVerified ? form.photographer + ' · 已认证' : '待项目负责人认证' }}</view>
        <text class="field-label">{{ manualPhoto ? '地点（相册照片需手填）' : '位置（优先定位）' }}</text>
        <view v-if="form.locationText && !manualLocation" class="readonly-value">{{ form.locationText }}</view>
        <view v-if="!manualPhoto" class="location-actions"><button class="secondary-button pressable location-primary" :disabled="busy" @tap="getLocation">{{ locating ? '正在定位…' : form.locationText ? '重新定位' : '获取当前位置' }}</button><button class="text-button pressable" :disabled="busy" @tap="manualLocation = !manualLocation">{{ manualLocation ? '收起手填' : '手填备用' }}</button></view>
        <input v-if="manualLocation" v-model="form.locationText" class="input" maxlength="120" :placeholder="manualPhoto ? '填写拍摄当时的实际地点' : '定位不可用时，填写现场地址'" :disabled="busy" @input="locationLabel = '手填位置'" />
        <text v-if="locationLabel === '当前定位' && form.locationText && context.sourceKind !== 'camera'" class="copy-note">这是此刻手机的位置，请确认适用于这张旧照片。</text>
        <text class="field-label">施工单位名称（底部色块）</text><input v-model="form.contractor" class="input" maxlength="100" placeholder="手填施工单位全称" :disabled="busy" />
        <view class="export-row"><text>高清导出</text><switch :checked="largeExport" :disabled="busy || previewOnly" @change="changeExportQuality" /></view>
      </view>
      <button v-if="cameraMode && shotTaken" class="secondary-button album-button" :disabled="busy" @tap="continueCamera">继续拍照</button>
    </template>
    <view v-if="error" class="error-card" role="alert"><text>{{ error }}</text><button v-if="showSettings" class="text-button pressable" @tap="openSettings">打开权限设置</button></view>
    <template v-if="context">
      <text v-if="!liveCamera" class="classify-note">上传后自动归类到施工单元；识别不到的照片送电脑端待分类，供人工筛选。</text>
      <text v-if="!canCaptureProject(activeProject)" class="copy-note">当前可制作水印并保存到手机，本项目未开通上传权限。</text>
      <button v-if="!liveCamera && canCaptureProject(activeProject)" class="primary-button pressable save-button" :disabled="busy || Boolean(uploadedBatchId)" @tap="uploadAuto">{{ uploading ? '正在准备上传…' : uploadedBatchId ? '已加入上传归类队列' : previewOnly ? '上传水印预览并归类' : '上传并自动归类' }}</button>
      <button v-if="!liveCamera" class="secondary-button pressable album-button" :disabled="busy" @tap="savePhoto">{{ saveLabel }}</button>
      <button v-if="uploadedBatchId" class="text-button queue-link pressable" @tap="openQueue">查看同步记录</button>
    </template>
  </view>
</template>

<style scoped>
.camera-stage { margin: 12px auto; position: relative; background: #000; overflow: hidden; border-radius: 12px; }
.live-camera, .camera-overlay { width: 100%; height: 100%; }
.camera-overlay { position: absolute; top: 0; left: 0; }
.camera-tools { display: flex; align-items:center; gap: 12px; margin: 12px 0; }
.camera-tools button { flex:1; font-size: 14px; padding: 0 8px; }
.camera-tools .camera-edit { flex: 1.5; }
.camera-shutter { width: 96px; height: 64px; border-radius: 32px; margin: 16px auto; font-size: 20px; }

.manual-datetime { display:grid; grid-template-columns:1fr 1fr; gap:12rpx; }
.division-search { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:12rpx; }
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
.location-actions { justify-content:flex-start; margin:10rpx 0; }.location-primary { flex:1; min-height:44px; font-size:25rpx; }.location-source { margin-right:auto; font-size:22rpx; color:var(--muted); }
.advanced-toggle { width:100%; display:flex; justify-content:space-between; align-items:center; min-height:44px; padding:0; background:transparent; color:var(--text); font-size:27rpx; }.advanced-toggle text:last-child { color:var(--primary-strong); font-size:24rpx; }
.option-row { display:flex; flex-wrap:wrap; gap:12rpx; }.option-chip { display:inline-flex; align-items:center; min-height:44px; padding:0 22rpx; background:var(--surface-2); border:1rpx solid var(--line); color:var(--muted); font-size:24rpx; border-radius:16rpx; }.option-chip.active { background:var(--primary-soft); color:var(--primary-strong); border-color:var(--primary-strong); }
.export-row { margin-top:24rpx; }.error-card { margin-top:24rpx; padding:20rpx; border-radius:18rpx; color:var(--danger); background:var(--surface-2); font-size:24rpx; line-height:1.5; }.save-button { margin-top:28rpx; }
.archive-target { display:block; margin-top:18rpx; color:var(--primary-strong); font-size:25rpx; line-height:1.5; }.classify-note { display:block; margin-top:26rpx; color:var(--muted); font-size:23rpx; line-height:1.6; }.album-button { width:100%; min-height:48px; margin-top:16rpx; font-size:26rpx; }.queue-link { display:flex; margin-top:14rpx; }
</style>
