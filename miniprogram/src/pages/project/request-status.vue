<script setup lang="ts">
import { themeStyle } from '@/services/theme'
import { computed, ref, watch } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { sessionState } from '@/services/auth'
import { clearJoinRequest, pendingJoinRequest, type ProjectJoinRequest } from '@/services/project-join-request'
import { loadBootstrap } from '@/stores/bootstrap'

const uniApi = uni
const requestId = ref('')
const request = ref<ProjectJoinRequest | null>(null)
const loading = ref(false)
const error = ref('')
const opening = ref(false)
const statusTitle = computed(() => request.value?.status === 'approved' ? '申请已通过' : request.value?.status === 'pending' ? '等待分享人审核' : request.value?.status === 'rejected' ? '申请未通过' : request.value ? '申请已失效' : '加入申请')
const statusCopy = computed(() => request.value?.status === 'approved' ? '现在可以打开项目，按获准权限使用。' : request.value?.status === 'pending' ? '申请已提交。分享人同意后，才能查看项目或上传照片。' : '请联系分享人核实，获取新的邀请后重新申请。')
const terminal = computed(() => request.value && ['rejected', 'expired', 'revoked'].includes(request.value.status))

async function refresh() {
  const account = sessionState.account
  if (!account || sessionState.stage !== 'authenticated' || loading.value) return
  const owner = String(account.id)
  loading.value = true
  error.value = ''
  try {
    const response = await mobileApi.listProjectJoinRequests()
    if (String(sessionState.account?.id || '') !== owner || sessionState.stage !== 'authenticated') return
    request.value = response.requests.find((item) => item.id === requestId.value && item.applicant_account_id === owner) || null
    if (!request.value) error.value = '未找到当前账号的申请，请刷新或联系分享人。'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '读取申请失败，请稍后重试' }
  finally { loading.value = false }
}
async function openProject() {
  const account = sessionState.account
  if (!account || request.value?.status !== 'approved' || opening.value) return
  opening.value = true
  error.value = ''
  try {
    const response = await loadBootstrap(account.id, request.value.project_id)
    if (sessionState.account?.id !== account.id) return
    if (!response.projects.some((item) => item.id === request.value?.project_id)) throw new Error('当前账号已无项目权限，请联系项目负责人。')
    clearJoinRequest(account.id)
    uni.reLaunch({ url: '/pages/home/index' })
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '打开项目失败' }
  finally { opening.value = false }
}
function applyAgain() {
  if (sessionState.account) clearJoinRequest(sessionState.account.id)
  uni.navigateTo({ url: '/pages/project/join' })
}
onLoad((query) => { requestId.value = String(query?.id || (sessionState.account ? pendingJoinRequest(sessionState.account.id) : '')) })
onShow(() => { void refresh() })
watch(() => sessionState.stage, (stage) => { if (stage === 'authenticated') void refresh(); else request.value = null })
</script>

<template>
  <page-meta :page-style="themeStyle" />
  <view class="page-shell no-tabs request-page">
    <PageHeader title="加入申请" :back="false" />
    <view class="request-card card">
      <text class="status-title">{{ statusTitle }}</text>
      <text v-if="request" class="project-name">{{ request.project_name }}</text>
      <text v-if="request" class="status-copy">{{ statusCopy }}</text>
      <view v-if="request" class="applicant"><text>{{ request.display_name }}</text><text>{{ request.phone }}</text></view>
      <text v-if="request?.reason" class="status-copy">{{ request.reason }}</text>
      <text v-if="error" class="error-copy" role="alert">{{ error }}</text>
      <button v-if="request?.status === 'approved'" class="primary-button pressable" :disabled="opening" @tap="openProject">{{ opening ? '正在打开…' : '打开项目' }}</button>
      <button v-else class="primary-button pressable" :disabled="loading" @tap="refresh">{{ loading ? '正在查询…' : '刷新审核结果' }}</button>
      <button v-if="terminal" class="text-button pressable" @tap="applyAgain">使用新的邀请码申请</button>
      <button class="text-button pressable" @tap="uniApi.reLaunch({ url: '/pages/home/index' })">返回工作台</button>
    </view>
  </view>
</template>

<style scoped>
.request-card { margin-top:36rpx; padding:34rpx 28rpx; }
.status-title { display:block; font-size:36rpx; font-weight:700; color:var(--text); }
.project-name { display:block; margin-top:18rpx; font-size:28rpx; color:var(--primary-strong); }
.status-copy { display:block; margin:20rpx 0; font-size:25rpx; line-height:1.7; color:var(--muted); }
.applicant { display:flex; flex-wrap:wrap; gap:20rpx; margin:24rpx 0 32rpx; font-size:26rpx; color:var(--text); }
.error-copy { display:block; margin:20rpx 0; font-size:24rpx; line-height:1.5; color:var(--danger); }
.text-button { display:flex; align-items:center; justify-content:center; min-height:44px; margin-top:16rpx; padding:0 20rpx; color:var(--muted); background:transparent; font-size:25rpx; }
</style>
