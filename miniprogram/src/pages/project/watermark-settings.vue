<script setup lang="ts">
import {ref} from 'vue'
import {onLoad} from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import {usePageTheme} from '@/services/theme'
const themeStyle = usePageTheme()
import {COMPANY_LOGOS} from '@/services/company-logos'
import {selectionStorage} from '@/stores/selection'
import {readProjectWatermark,saveProjectWatermark} from '@/services/project-watermark'
const project=selectionStorage.getProject(),owner=selectionStorage.getOwner()
const logoId=ref('crec'),contractor=ref(''),canManage=ref(false),loading=ref(true),saving=ref(false),error=ref('')
function current(){return selectionStorage.getOwner()===owner && selectionStorage.getProject().id===project.id}
onLoad(async()=>{try {const value=await readProjectWatermark(String(project.id));if(current()){logoId.value=value.settings.logo_id;contractor.value=value.settings.contractor;canManage.value=value.can_manage}}catch(e){error.value=e instanceof Error?e.message:'读取失败'}finally{loading.value=false}})
async function save(){if(!canManage.value||saving.value||!current())return;saving.value=true;error.value='';try{await saveProjectWatermark(String(project.id),{logo_id:logoId.value,contractor:contractor.value.trim()});if(current()){uni.showToast({title:'已统一设置',icon:'success'});uni.navigateBack()}}catch(e){error.value=e instanceof Error?e.message:'保存失败'}finally{saving.value=false}}
</script>
<template>
  <page-meta :page-style="themeStyle"/>
  <view class="page-shell no-tabs settings-page" :style="themeStyle">
    <PageHeader title="项目水印设置"/>
    <text class="project-title">{{project.name}}</text><text class="intro">设置一次，所有项目成员拍照时自动使用。</text>
    <view v-if="loading" class="empty-state">正在读取…</view>
    <template v-else>
      <view class="card settings-section"><text class="section-title">企业标志</text><view class="logo-grid"><button v-for="logo in COMPANY_LOGOS" :key="logo.id" class="logo-choice" :class="{selected:logoId===logo.id}" :disabled="!canManage||saving" @tap="logoId=logo.id"><image :src="logo.path" mode="aspectFit"/><text>{{logo.name}}</text><text v-if="logoId===logo.id" class="chosen">✓</text></button></view></view>
      <view class="card settings-section"><text class="section-title">施工单位</text><input v-model="contractor" class="input" maxlength="120" placeholder="填写施工单位全称" :disabled="!canManage||saving"/></view>
      <text v-if="!canManage" class="intro">由项目负责人或管理员统一维护。</text>
      <button v-if="canManage" class="primary-button save-settings" :disabled="saving" @tap="save">{{saving?'正在保存…':'保存项目设置'}}</button>
    </template>
    <text v-if="error" class="error-text">{{error}}</text>
  </view>
</template>
<style scoped>
.project-title{display:block;font-size:32rpx;font-weight:600;margin:20rpx 0 12rpx}.intro{display:block;color:var(--muted);font-size:25rpx;line-height:1.6;margin-bottom:26rpx}.settings-section{padding:26rpx;margin-bottom:24rpx}.logo-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18rpx;margin-top:22rpx}.logo-choice{position:relative;display:flex;flex-direction:column;align-items:center;gap:14rpx;min-height:156rpx;padding:18rpx;border:2rpx solid var(--line);border-radius:18rpx;background:var(--surface);color:var(--text);font-size:25rpx}.logo-choice.selected{border-color:var(--primary-strong);background:var(--primary-soft)}.logo-choice image{width:160rpx;height:74rpx;background:#fff;border-radius:8rpx}.chosen{position:absolute;top:8rpx;right:12rpx;color:var(--primary-strong)}.settings-section .input{margin-top:22rpx}.save-settings{width:100%;margin-top:28rpx}.error-text{display:block;color:var(--danger);margin-top:24rpx}
</style>
