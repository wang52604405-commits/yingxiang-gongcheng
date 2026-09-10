<script setup lang="ts">
import { usePageTheme } from '@/services/theme'
const themeStyle = usePageTheme()
import { beginWatermarkDivision, consumeWatermarkDivision, watermarkDivisionFields } from '@/services/watermark-division'
import { computed, reactive, ref, watch } from 'vue'
import { onLoad, onReady, onShow, onHide, onResize, onUnload } from '@dcloudio/uni-app'
import UiIcon from '@/components/UiIcon.vue'
import { cachedProjectWatermark, readProjectWatermark } from '@/services/project-watermark'
import PageHeader from '@/components/PageHeader.vue'
import { selectionStorage } from '@/stores/selection'
import { sessionState } from '@/services/auth'
import { consumeWatermarkContext, watermarkContextMatches, watermarkUploadDraft, type WatermarkContext } from '@/services/watermark-context'
import { generatePhotoWatermark, saveWatermarkToAlbum } from '@/services/photo-watermark'
import { COMPANY_LOGOS } from '@/services/company-logos'
import { queueRuntime } from '@/services/queue-runtime'
import { canCaptureProject, capturePermissionMessage } from '@/services/project-membership'
import { mobileApi } from '@/api/mobile'
import type { ProjectSummary } from '@/types/domain'

const cameraMode = ref(false), shotTaken = ref(false), editingCamera = ref(false), cameraReady = ref(false), cameraActive = ref(true), shooting = ref(false)
const cameraPosition = ref<'back'|'front'>('back'), cameraFlash = ref<'off'|'auto'>('off'), cameraWidth=ref(343), cameraHeight=ref(457)
const overlayFrames=ref(['','']), overlayActive=ref(0); function overlayLoaded(i:number){overlayActive.value=i}
let overlayTimer:ReturnType<typeof setTimeout>|undefined, clockTimer:ReturnType<typeof setInterval>|undefined
const context=ref<WatermarkContext|null>(null), activeProject=ref(selectionStorage.getProject())
const form=reactive({project:'',title:'',photographer:'',photoDate:'',sitePart:'',locationText:'',unitProjectName:'',partName:'',unitName:'',unitCode:'',constructionContent:'',capturedAt:'',contractor:''})
const locationLabel=ref<'当前定位'|'手填位置'|'拍摄位置'>('手填位置'), manualDate=ref(''), manualTime=ref('')
const manualPhoto=computed(()=>context.value?.sourceKind!=='camera'), projectLocationFixed=ref(false), logoIndex=ref(0)
const logoNames=['不加企业标志',...COMPANY_LOGOS.map(i=>i.name)], largeExport=ref(false), rendering=ref(false), saving=ref(false), uploading=ref(false), uploadedBatchId=ref('')
const busy=computed(()=>shooting.value||saving.value||uploading.value), error=ref(''), projectSettingsManage=ref(false); let renderGeneration=0
const cameraPageStyle=computed(()=>liveCamera.value&&!editingCamera.value?themeStyle.value+';--bg:#070b0d;--text:#ffffff;--muted:#b0bec4;--top:#070b0d;--header-text:#ffffff;--header-muted:#b0bec4;--line:#273138;--surface:#122024;--surface-2:#17282d;--primary-strong:#42d7c2;--danger:#ff6b66;--on-primary:#041a1a':themeStyle.value)
const liveCamera=computed(()=>cameraMode.value&&!shotTaken.value), divisionSummary=computed(()=>[form.partName,form.unitName].filter(Boolean).join(' / ')||'选择施工部位')
const showSettings=ref(false), preview=ref<{tempFilePath:string;width:number;height:number}|null>(null), dirty=ref(true); let alive=true, choosingHierarchy=false; const divisionKeyword=ref('')
const photographerVerified=computed(()=>activeProject.value.photographer_verified===true&&Boolean(activeProject.value.photographer_name))
function dateOnly(value:string){const d=new Date(value);if(!Number.isFinite(d.getTime()))return'';const two=(n:number)=>String(n).padStart(2,'0');return `${d.getFullYear()}-${two(d.getMonth()+1)}-${two(d.getDate())}`}
const timeText=computed(()=>dateOnly(form.capturedAt)||form.photoDate||'未取得拍摄日期')
function preferenceKey(){return context.value?`engineering-image:watermark-template:v1:${context.value.owner}:${context.value.projectId}`:''}
function storedPreference(){const k=preferenceKey();if(!k)return null;const s=uni.getStorageSync(k) as any;return s&&typeof s==='object'?s:null}
function applyPreference(s:any){Object.assign(form,{unitProjectName:String(s?.unitProjectName||''),partName:String(s?.partName||''),unitName:String(s?.unitName||''),unitCode:String(s?.unitCode||''),constructionContent:String(s?.constructionContent||'')})}
function clearVariableWatermark(){Object.assign(form,{unitProjectName:'',partName:'',unitName:'',unitCode:'',constructionContent:''})}
function promptPreviousWatermark(){if(!cameraMode.value)return;const s=storedPreference();if(!s||![s.unitProjectName,s.partName,s.unitName,s.constructionContent].some(v=>String(v||'').trim())){clearVariableWatermark();return}uni.showModal({title:'沿用上次水印？',content:[s.partName,s.unitName,s.constructionContent].filter(Boolean).join(' / ')||'已保存上次施工水印',confirmText:'沿用',cancelText:'重新填写',success:({confirm})=>{if(confirm)applyPreference(s);else clearVariableWatermark();dirty.value=true;scheduleOverlay()}})}
function savePreference(){if(!cameraMode.value)return;const k=preferenceKey();if(k)uni.setStorageSync(k,{unitProjectName:form.unitProjectName,partName:form.partName,unitName:form.unitName,unitCode:form.unitCode,constructionContent:form.constructionContent})}
function chooseHierarchy(){if(!busy.value&&sameContext()){beginWatermarkDivision(selectionStorage.getOwner(),String(activeProject.value.id));choosingHierarchy=true;uni.navigateTo({url:'/pages/destination/select?scope=engineering&return=watermark&keyword='+encodeURIComponent(divisionKeyword.value.trim())})}}
async function refreshIdentity(){if(!context.value)return;try{const r=await mobileApi.projects();if(!alive||!sameContext())return;const p=r.projects.find((i:ProjectSummary)=>String(i.id)===context.value?.projectId);if(!p)throw new Error('当前账号已无此项目权限');activeProject.value=p;selectionStorage.setProject(p);form.project=p.name;form.photographer=p.photographer_name||''}catch(reason){if(!photographerVerified.value)showError(reason)}}
const previewOnly=computed(()=>context.value?.sourceQuality==='preview'), saveLabel=computed(()=>saving.value?'正在保存…':previewOnly.value?'保存水印预览到相册':'保存水印照片到相册'), previewImage=computed(()=>preview.value?.tempFilePath||context.value?.sourcePath||'')
function sameContext(){return Boolean(context.value&&watermarkContextMatches(context.value,selectionStorage.getOwner(),String(selectionStorage.getProject().id||''))&&String(sessionState.account?.id||'')===context.value.owner)}
function requireContext(){if(!alive||!sameContext()||!context.value)throw new Error('账号或工程已切换，请返回重新选择照片');return context.value}
function showError(reason:unknown){error.value=reason instanceof Error?reason.message:'操作失败，请重试';showSettings.value=Boolean((reason as any)?.canOpenSettings)}
async function renderLatest(){const source=requireContext(),generation=++renderGeneration,renderingLive=liveCamera.value;if(!photographerVerified.value)throw new Error('拍摄者姓名尚未认证，请联系项目负责人审核');if(manualPhoto.value&&(!manualDate.value||!manualTime.value||!form.locationText.trim()))throw new Error('请填写这张照片的时间和地点');const result=await generatePhotoWatermark(source.sourcePath,{companyName:COMPANY_LOGOS[logoIndex.value-1]?.name||'',project:form.project,unitProjectName:form.unitProjectName,partName:form.partName,unitName:form.unitName,constructionContent:form.constructionContent,capturedAt:form.capturedAt||form.photoDate,photographer:form.photographer,contractor:form.contractor,location:form.locationText.trim()?{label:locationLabel.value,text:form.locationText.trim()}:undefined},{maxEdge:largeExport.value?4096:2048,overlaySize:liveCamera.value?{width:Math.round(cameraWidth.value*3),height:Math.round(cameraHeight.value*3)}:undefined,logoPath:logoIndex.value?COMPANY_LOGOS[logoIndex.value-1]?.path:undefined,logoCrop:logoIndex.value?COMPANY_LOGOS[logoIndex.value-1]?.symbolCrop:undefined});requireContext();if(generation!==renderGeneration||renderingLive!==liveCamera.value)return result;preview.value=result;if(renderingLive){const target=1-overlayActive.value,old=overlayFrames.value[target];overlayFrames.value[target]=result.tempFilePath;if(old&&old!==result.tempFilePath)try{(globalThis as any).wx?.getFileSystemManager().unlink({filePath:old,fail(){}})}catch{}}dirty.value=false;return result}
async function updatePreview(){if(busy.value||rendering.value||!context.value)return;rendering.value=true;error.value='';try{await renderLatest()}catch(r){if(alive)showError(r)}finally{rendering.value=false}}
async function savePhoto(){if(busy.value||liveCamera.value)return;saving.value=true;error.value='';try{const output=dirty.value||!preview.value?await renderLatest():preview.value;await saveWatermarkToAlbum(output.tempFilePath);if(alive&&sameContext())uni.showToast({title:'水印副本已保存到相册',icon:'success'})}catch(r){if(alive)showError(r)}finally{saving.value=false}}
async function uploadAuto(){if(busy.value||liveCamera.value||uploadedBatchId.value)return;uploading.value=true;error.value='';let captureId='';try{const source=requireContext(),project=selectionStorage.getProject(),denied=capturePermissionMessage(project);if(denied)throw new Error(denied.content);const output=dirty.value||!preview.value?await renderLatest():preview.value;captureId=`watermark:${output.tempFilePath}`;const title=[form.unitName,form.constructionContent.trim()].filter(Boolean).join('—'),sitePart=[form.unitCode,form.unitProjectName,form.partName,form.unitName,form.constructionContent.trim()].filter(Boolean).join(' / ');const batch=await queueRuntime.enqueue([output.tempFilePath],watermarkUploadDraft(source,{...form,title,sitePart},project.name,captureId));uploadedBatchId.value=batch.client_batch_id;savePreference();uni.showToast({title:'已加入上传归类队列',icon:'success'})}catch(r){if(alive)showError(r)}finally{uploading.value=false}}
function applySharedSettings(v:ReturnType<typeof cachedProjectWatermark>){projectSettingsManage.value=v.can_manage;logoIndex.value=Math.max(0,COMPANY_LOGOS.findIndex(i=>i.id===v.settings.logo_id)+1);form.contractor=v.settings.contractor;projectLocationFixed.value=Boolean(v.settings.location_text.trim());form.locationText=v.settings.location_text.trim();if(form.locationText)locationLabel.value='手填位置'}
async function refreshSharedSettings(){if(!context.value||!sameContext())return;try{applySharedSettings(await readProjectWatermark(context.value.projectId))}catch{}}
function openProjectSettings(){if(projectSettingsManage.value)uni.navigateTo({url:'/pages/project/watermark-settings'})} function openAlbum(){uni.redirectTo({url:'/pages/upload/index?source=album&autopick=1',animationType:'none'} as any)} function previewLarge(){if(previewImage.value)uni.previewImage({current:previewImage.value,urls:[previewImage.value]})} function openSettings(){uni.openSetting({})}
onLoad(q=>{cameraMode.value=q?.camera==='1';resizeCamera();const now=new Date().toISOString();const value:WatermarkContext|null=cameraMode.value?{owner:selectionStorage.getOwner(),projectId:String(activeProject.value.id||''),sourcePath:'camera-pending',sourceQuality:'original',sourceKind:'camera',project:activeProject.value.name,title:'',photographer:'',photoDate:dateOnly(now),capturedAt:now,scope:selectionStorage.getUploadPreset()?.scope||'engineering',category:selectionStorage.getUploadPreset()?.category||'construction'}:consumeWatermarkContext(selectionStorage.getOwner(),String(selectionStorage.getProject().id||''));if(!value||String(sessionState.account?.id||'')!==value.owner){error.value='照片已失效，请返回重新选择';return}context.value=value;Object.assign(form,{project:activeProject.value.name,constructionContent:value.title===value.unitName?'':value.title,photographer:activeProject.value.photographer_name||'',photoDate:value.photoDate||dateOnly(value.capturedAt||''),capturedAt:value.capturedAt||'',unitProjectName:value.unitProjectName||'',partName:value.partName||'',unitName:value.unitName||''});if(value.sourceKind!=='camera'){form.photoDate='';form.capturedAt=''}applySharedSettings(cachedProjectWatermark(value.projectId));if(cameraMode.value)promptPreviousWatermark()})
onReady(async()=>{await Promise.all([refreshIdentity(),refreshSharedSettings()]);if(!manualPhoto.value)await updatePreview()})
onShow(()=>{cameraActive.value=true;activeProject.value=selectionStorage.getProject();if(context.value)void refreshSharedSettings();if(choosingHierarchy&&context.value&&sameContext()){choosingHierarchy=false;const s=consumeWatermarkDivision(selectionStorage.getOwner(),String(activeProject.value.id));if(s){Object.assign(form,watermarkDivisionFields(s.assignment));savePreference()}}if(liveCamera.value)scheduleOverlay()})
onHide(()=>{cameraActive.value=false;cameraReady.value=false;clearTimeout(overlayTimer)});onResize(resizeCamera);onUnload(()=>{alive=false;clearTimeout(overlayTimer);clearInterval(clockTimer)})
watch([form,locationLabel,logoIndex,largeExport],()=>{dirty.value=true;uploadedBatchId.value='';scheduleOverlay()},{deep:true});watch([()=>form.unitProjectName,()=>form.partName,()=>form.unitName,()=>form.unitCode,()=>form.constructionContent],savePreference)
function resizeCamera(){const s=uni.getSystemInfoSync(),land=s.windowWidth>s.windowHeight;cameraWidth.value=land?Math.max(180,Math.min(s.windowWidth-32,(s.windowHeight-170)*4/3)):Math.min(s.windowWidth-32,Math.max(180,(s.windowHeight-290)*3/4));cameraHeight.value=cameraWidth.value*(land?3/4:4/3);scheduleOverlay()}
function scheduleOverlay(){clearTimeout(overlayTimer);if(!alive||!liveCamera.value||!cameraActive.value||editingCamera.value)return;overlayTimer=setTimeout(()=>{if(busy.value||rendering.value)scheduleOverlay();else void updatePreview()},350)}
function editCameraWatermark(){editingCamera.value=true;cameraReady.value=false;clearTimeout(overlayTimer)} function returnToCamera(){editingCamera.value=false;const now=new Date().toISOString();form.capturedAt=now;form.photoDate=dateOnly(now);scheduleOverlay();uni.pageScrollTo({scrollTop:0,duration:0})}
function onCameraError(e:any){cameraReady.value=false;error.value=e?.detail?.errMsg||'相机未能打开，请允许相机权限后重试';showSettings.value=true}
async function takeWatermarkPhoto(){if(busy.value||!cameraReady.value||!photographerVerified.value)return;shooting.value=true;error.value='';clearTimeout(overlayTimer);try{const capturedAt=new Date().toISOString();const result=await new Promise<any>((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('拍照超时，请重试')),20000);uni.createCameraContext().takePhoto({quality:'high',success:r=>{clearTimeout(timer);resolve(r)},fail:r=>{clearTimeout(timer);reject(new Error(r.errMsg||'拍照失败，请重试'))}})});if(!result.tempImagePath)throw new Error('未取得照片，请重新拍摄');context.value!.sourcePath=result.tempImagePath;context.value!.capturedAt=capturedAt;context.value!.photoDate=dateOnly(capturedAt);form.capturedAt=capturedAt;form.photoDate=dateOnly(capturedAt);shotTaken.value=true;preview.value=null;dirty.value=true;savePreference();await renderLatest()}catch(r){if(alive)showError(r)}finally{shooting.value=false}}
function continueCamera(){if(busy.value)return;shotTaken.value=false;cameraReady.value=false;preview.value=null;uploadedBatchId.value='';dirty.value=true;const now=new Date().toISOString();context.value!.sourcePath='camera-pending';context.value!.capturedAt=now;context.value!.photoDate=dateOnly(now);form.capturedAt=now;form.photoDate=dateOnly(now);scheduleOverlay()}
onReady(()=>{if(cameraMode.value)clockTimer=setInterval(()=>{if(liveCamera.value&&cameraActive.value&&!busy.value){const now=new Date().toISOString();form.capturedAt=now;form.photoDate=dateOnly(now)}},1000)})
function openQueue(){uni.switchTab({url:'/pages/queue/index'})}
</script>
<template>
  <page-meta :page-style="cameraPageStyle" />
  <view class="page-shell no-tabs watermark-page" :style="cameraPageStyle" :class="{ 'camera-view': liveCamera && !editingCamera }">
    <PageHeader :title="liveCamera ? '水印相机' : previewOnly ? '水印预览图' : '水印照片'" />
    <template v-if="context">
      <template v-if="liveCamera">
        <view v-if="!editingCamera" class="camera-stage" :style="{ width: cameraWidth + 'px', height: cameraHeight + 'px' }">
          <camera v-if="cameraActive" id="watermark-camera" class="live-camera" mode="normal" resolution="high" :device-position="cameraPosition" :flash="cameraFlash" @initdone="cameraReady = true" @error="onCameraError" @stop="cameraReady = false">
            <cover-image v-for="(frame,index) in overlayFrames" :key="index" class="camera-overlay" :src="frame" :style="{opacity:index===overlayActive?1:0}" @load="overlayLoaded(index)" @tap="editCameraWatermark" />
          </camera>
        </view>
        <view v-if="!editingCamera" class="camera-controls">
          <button class="camera-watermark-entry" :disabled="busy" @tap="editCameraWatermark"><view><text class="camera-entry-title">编辑水印</text><text class="camera-entry-subtitle">{{ divisionSummary }}</text></view><text class="camera-entry-arrow">›</text></button>
          <view class="capture-controls-row"><button class="camera-side" :disabled="busy" @tap="openAlbum"><UiIcon name="gallery" :size="24"/><text>相册</text></button><button class="camera-shutter" aria-label="拍照" :disabled="busy || !cameraReady || !photographerVerified" @tap="takeWatermarkPhoto"><view class="shutter-disc"/></button><button class="camera-side" :disabled="busy" @tap="cameraPosition = cameraPosition === 'back' ? 'front' : 'back'"><text class="flip-icon">↻</text><text>翻转</text></button></view>
          <button class="camera-flash" :disabled="busy" @tap="cameraFlash = cameraFlash === 'off' ? 'auto' : 'off'">{{ cameraFlash === 'off' ? '闪光灯关闭' : '闪光灯自动' }}</button>
        </view>
        <button v-else class="primary-button edit-done" :disabled="busy" @tap="returnToCamera">完成 · 返回拍照</button>
      </template>
      <button v-if="!liveCamera" class="watermark-preview pressable" @tap="previewLarge"><image :src="previewImage" mode="aspectFit" /><text v-if="rendering" class="preview-badge">正在生成预览…</text><text v-else-if="dirty && preview" class="preview-badge">设置已更改，请更新预览</text></button>
      <view v-if="!liveCamera" class="preview-caption"><text>{{ preview ? `${preview.width} × ${preview.height}` : '原始画面' }}</text><button class="text-button pressable" :disabled="busy" @tap="updatePreview">更新预览</button></view>
      <text v-if="previewOnly" class="quality-note">当前使用预览图，保存和上传的清晰度均受预览图限制。</text>
      <text v-if="!liveCamera" class="copy-note">生成带水印的副本，原照片保持不变。</text>
      <view v-if="!liveCamera || editingCamera" class="compact-editor">
        <text class="editor-project">{{ form.project }}</text>
        <view class="edit-card card">
          <text class="section-title">这次拍什么</text>
          <button class="division-choice" :disabled="busy" @tap="chooseHierarchy"><view><text class="field-label">施工部位</text><text class="division-value">{{ divisionSummary }}</text></view><text>›</text></button>
          <input v-model="divisionKeyword" class="input search-division" maxlength="80" placeholder="输入部位名称或编码搜索" confirm-type="search" @confirm="chooseHierarchy" />
          <text class="field-label">施工内容</text><textarea v-model="form.constructionContent" class="input content-input" maxlength="60" placeholder="如：底板钢筋绑扎检查" :disabled="busy" auto-height />
        </view>
        <view class="edit-card card">
          <view class="field-heading"><text class="section-title">拍摄地点</text><button v-if="projectSettingsManage" class="text-button" @tap="openProjectSettings">{{ projectLocationFixed ? '修改固定地点' : '设置固定地点' }}</button><text v-else class="fixed-badge">项目固定</text></view>
          <input v-model="form.locationText" class="input" maxlength="120" :placeholder="projectLocationFixed ? '' : '请由项目负责人统一设置拍摄地点'" :disabled="busy || projectLocationFixed || !projectSettingsManage" />
          <view v-if="manualPhoto" class="manual-datetime"><picker mode="date" :value="manualDate" :disabled="busy" @change="manualDate = $event.detail.value"><view class="input date-input">{{ manualDate || '拍摄日期' }}</view></picker><picker mode="time" :value="manualTime" :disabled="busy" @change="manualTime = $event.detail.value"><view class="input date-input">{{ manualTime || '拍摄时间' }}</view></picker></view>
          <view v-else class="automatic-info"><text>{{ timeText }}</text><text>{{ photographerVerified ? form.photographer : '拍摄者待认证' }}</text></view>
        </view>
        <view class="shared-settings-summary"><view><text class="shared-company">{{ logoNames[logoIndex] }}</text><text>{{ form.contractor || '施工单位待负责人设置' }}</text></view><button v-if="projectSettingsManage" class="text-button" @tap="openProjectSettings">项目设置</button><text v-else class="shared-owner-note">负责人统一设置</text></view>
      </view>
      <button v-if="cameraMode && shotTaken" class="secondary-button album-button" :disabled="busy" @tap="continueCamera">继续拍照</button>
    </template>
    <view v-if="error" class="error-card" role="alert"><text>{{ error }}</text><button v-if="showSettings" class="text-button pressable" @tap="openSettings">打开权限设置</button></view>
    <template v-if="context">
      <text v-if="!liveCamera" class="classify-note">上传后自动归类到施工单元；识别不到的照片送电脑端待分类，供人工筛选。</text>
      <text v-if="!liveCamera && !canCaptureProject(activeProject)" class="copy-note">当前可制作水印并保存到手机，本项目未开通上传权限。</text>
      <button v-if="!liveCamera && canCaptureProject(activeProject)" class="primary-button pressable save-button" :disabled="busy || Boolean(uploadedBatchId)" @tap="uploadAuto">{{ uploading ? '正在准备上传…' : uploadedBatchId ? '已加入上传归类队列' : previewOnly ? '上传水印预览并归类' : '上传并自动归类' }}</button>
      <button v-if="!liveCamera" class="secondary-button pressable album-button" :disabled="busy" @tap="savePhoto">{{ saveLabel }}</button>
      <button v-if="uploadedBatchId" class="text-button queue-link pressable" @tap="openQueue">查看同步记录</button>
    </template>
  </view>
</template>

<style scoped>
.camera-stage { margin: 0 auto; position: relative; background: #000; overflow: hidden; border-radius: 0; }
.live-camera, .camera-overlay { width: 100%; height: 100%; }
.camera-overlay { position: absolute; top: 0; left: 0; }
.camera-tools { display: flex; align-items:center; gap: 12px; margin: 12px 0; }
.camera-tools button { flex:1; font-size: 14px; padding: 0 8px; }
.camera-tools .camera-edit { flex: 1.5; }
.camera-view { padding: 0 0 220px; background:#070b0d; color:#fff; }
.camera-controls { position:fixed; left:0; right:0; bottom:0; padding:14px 24px calc(12px + env(safe-area-inset-bottom)); background:#070b0d; }
.camera-watermark-entry { display:flex; align-items:center; justify-content:space-between; width:100%; max-width:420px; margin:0 auto 14px; padding:12px 16px; border:1px solid #344047; border-radius:16px; background:#172127; color:#fff; text-align:left; }
.camera-entry-title { display:block; font-size:15px; font-weight:600; }.camera-entry-subtitle { display:block; max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-top:4px; font-size:12px; color:#b8c5cc; }.camera-entry-arrow { font-size:26px; }
.capture-controls-row { display:flex; align-items:center; justify-content:space-around; max-width:420px; margin:auto; }
.camera-side[disabled] { background:transparent; color:#e4edf1; }.camera-watermark-entry[disabled] { background:#172127; color:#fff; }
.camera-side { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:5px; width:64px; min-height:64px; color:#e4edf1; font-size:11px; background:transparent; }.flip-icon { font-size:32px; line-height:32px; }
.camera-shutter { display:flex; align-items:center; justify-content:center; width:76px; height:76px; margin:0; padding:5px; border:3px solid #fff; border-radius:50%; background:transparent; }.shutter-disc { width:100%; height:100%; border-radius:50%; background:#fff; }.camera-shutter[disabled] { opacity:.5; background:transparent; }.camera-flash { display:block; margin:10px auto 0; color:#b8c5cc; background:transparent; font-size:11px; padding:4px 12px; }
.editor-project { display:block; margin:20rpx 0; color:var(--muted); font-size:24rpx; }.compact-editor .edit-card { margin-top:20rpx; padding:26rpx; border-radius:24rpx; }.division-choice { display:flex; justify-content:space-between; align-items:center; width:100%; margin:16rpx 0; text-align:left; color:var(--text); }.division-value { display:block; font-size:28rpx; font-weight:600; }.field-heading { display:flex; align-items:center; justify-content:space-between; margin-bottom:20rpx; }.content-input { min-height:88rpx; box-sizing:border-box; }.automatic-info { display:flex; justify-content:space-between; gap:18rpx; margin-top:20rpx; color:var(--muted); font-size:23rpx; }.automatic-info text:first-child{color:var(--text);font-variant-numeric:tabular-nums}.fixed-badge{color:var(--muted);font-size:22rpx}.shared-settings-summary { display:flex; justify-content:space-between; align-items:center; gap:20rpx; margin:26rpx 0; color:var(--muted); font-size:23rpx; }.shared-settings-summary view { flex:1; min-width:0; }.shared-settings-summary text { display:block; }.shared-company { color:var(--text); margin-bottom:6rpx; }.edit-done { margin-top:16rpx; }
.manual-datetime { display:grid; grid-template-columns:1fr 1fr; gap:12rpx; }
.division-search { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:12rpx; }
.readonly-value { color:var(--text); font-size:26rpx; line-height:1.5; padding:14rpx 0; }.hierarchy-row { display:grid; grid-template-columns:130rpx 1fr; gap:12rpx; padding:15rpx 0; border-bottom:1rpx solid var(--line); font-size:24rpx; line-height:1.5; }.hierarchy-row text:first-child { color:var(--muted); }
.watermark-page { padding-bottom:calc(48rpx + var(--safe-bottom)); }
.watermark-preview { position:relative; display:grid; place-items:center; width:100%; height:500rpx; padding:0; overflow:hidden; border-radius:24rpx; background:#071215; }.watermark-preview image { width:100%; height:100%; }
.preview-badge { position:absolute; bottom:16rpx; left:16rpx; right:16rpx; padding:10rpx; border-radius:10rpx; color:white; background:rgba(0,0,0,.65); font-size:22rpx; }
.preview-caption,.field-heading,.location-actions,.export-row { display:flex; align-items:center; justify-content:space-between; gap:16rpx; color:var(--muted); font-size:23rpx; }.field-heading { margin-top:18rpx; }.field-heading .field-label { margin:0; }
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