<script setup lang="ts">
import { usePageTheme } from '@/services/theme'
const themeStyle = usePageTheme()
import { computed, ref, watch } from 'vue'
import { onLoad, onUnload } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { sessionState } from '@/services/auth'
import { normalizeInviteCode, consumePendingInvite, peekPendingInvite, rememberPendingInvite, inviteCodeForJoinPage, clearDiscardedInviteEntry, invalidatePendingInvite, isInvalidInviteError } from '@/services/pending-invite'
import { PROJECT_ROLE_LABELS } from '@/services/project-membership'
import { applyBootstrap, loadBootstrap } from '@/stores/bootstrap'
import { rememberJoinRequest, validateJoinApplicant } from '@/services/project-join-request'
import type { ProjectInvite } from '@/types/domain'

const code = ref('')
const displayName = ref('')
const phone = ref('')
const preview = ref<ProjectInvite | null>(null)
const loading = ref(false)
const joining = ref(false)
const error = ref('')
const canJoin = computed(() => sessionState.stage === 'authenticated' && Boolean(preview.value?.project.id) && !loading.value && !joining.value)
const joinLabel = computed(() => joining.value ? '提交中…' : preview.value?.already_joined ? '打开项目' : '提交加入申请')
let previewTimer: ReturnType<typeof setTimeout> | null = null
let previewVersion = 0

async function loadPreview(expectedCode = code.value) {
  const normalized = normalizeInviteCode(expectedCode)
  if (normalized.length !== 10 || sessionState.stage !== 'authenticated' || !sessionState.account) return
  const version = ++previewVersion
  loading.value = true
  error.value = ''
  try {
    const response = await mobileApi.previewProjectInvite(normalized)
    if (version === previewVersion && code.value === normalized && sessionState.stage === 'authenticated') preview.value = response.invite
  } catch (reason) {
    if (version === previewVersion) {
      preview.value = null
      if (isInvalidInviteError(reason)) invalidatePendingInvite(normalized)
      error.value = reason instanceof Error ? reason.message : '邀请码不可用'
    }
  } finally {
    if (version === previewVersion) loading.value = false
  }
}

watch(code, (value) => {
  const normalized = normalizeInviteCode(value)
  if (normalized !== value) {
    code.value = normalized
    return
  }
  preview.value = null
  error.value = ''
  if (previewTimer) clearTimeout(previewTimer)
  if (normalized.length === 10) rememberPendingInvite(normalized)
  if (normalized.length === 10 && sessionState.stage === 'authenticated') previewTimer = setTimeout(() => { void loadPreview(normalized) }, 220)
})

watch(() => sessionState.stage, (stage) => {
  previewVersion += 1
  if (stage === 'authenticated') void loadPreview()
  else { preview.value = null; loading.value = false }
})

async function joinProject() {
  const account = sessionState.account
  if (!account || !canJoin.value) return
  const joiningCode = code.value
  joining.value = true
  error.value = ''
  try {
    if (preview.value?.already_joined) {
      await loadBootstrap(account.id, preview.value.project.id)
      if (peekPendingInvite() === joiningCode) consumePendingInvite()
      uni.reLaunch({ url: '/pages/home/index' })
      return
    }
    const validationError = validateJoinApplicant(displayName.value, phone.value)
    if (validationError) throw new Error(validationError)
    const response = await mobileApi.joinProjectInvite(joiningCode, displayName.value.trim(), phone.value.trim())
    if (sessionState.account?.id !== account.id || sessionState.stage !== 'authenticated') return
    if (response.join_request && response.join_request.status !== 'approved') {
      if (response.join_request.applicant_account_id !== String(account.id)) throw new Error('申请账号不匹配，请重试')
      rememberJoinRequest(account.id, response.join_request.id)
      if (peekPendingInvite() === joiningCode) consumePendingInvite()
      uni.reLaunch({ url: `/pages/project/request-status?id=${encodeURIComponent(response.join_request.id)}` })
      return
    }
    if (!response.project || !(response.already_member || response.join_request?.status === 'approved')) throw new Error('申请响应不完整，请重试')
    if (response.bootstrap) applyBootstrap(account.id, response.bootstrap, response.project.id)
    else await loadBootstrap(account.id, response.project.id)
    if (peekPendingInvite() === joiningCode) consumePendingInvite()
    uni.reLaunch({ url: '/pages/home/index' })
  } catch (reason) {
    if (isInvalidInviteError(reason)) invalidatePendingInvite(joiningCode)
    error.value = reason instanceof Error ? reason.message : '加入项目失败'
  } finally { joining.value = false }
}

function backHome() {
  if (code.value && peekPendingInvite() === code.value) consumePendingInvite()
  uni.reLaunch({ url: '/pages/home/index' })
}

onLoad((query) => {
  code.value = inviteCodeForJoinPage(query)
  if (!code.value && (query?.code || query?.invite) && sessionState.stage === 'authenticated') { clearDiscardedInviteEntry(); uni.reLaunch({ url: '/pages/home/index' }) }
})
onUnload(() => {
  if (previewTimer) clearTimeout(previewTimer)
  previewVersion += 1
  if (sessionState.stage === 'authenticated' && !joining.value && code.value && peekPendingInvite() === code.value) consumePendingInvite()
})

</script>

<template>
  <page-meta :page-style="themeStyle" />
  <view class="page-shell no-tabs join-page" :style="themeStyle">
    <PageHeader title="加入项目" />
    <text class="field-label code-label">邀请码</text>
    <input v-model="code" class="input invite-input" maxlength="10" type="text" placeholder="输入 10 位邀请码" placeholder-class="input-placeholder" />
    <view v-if="loading" class="preview-loading"><view class="loading-spinner" /><text>正在确认…</text></view>
    <view v-else-if="preview" class="project-preview card">
      <text class="preview-name">{{ preview.project.name }}</text>
      <text class="preview-meta">{{ PROJECT_ROLE_LABELS[preview.role] }}<template v-if="preview.inviter_name"> · {{ preview.inviter_name }}邀请</template></text>
    </view>
    <view v-if="!preview?.already_joined">
      <text class="field-label">真实姓名</text><input v-model="displayName" class="input" maxlength="60" placeholder="填写真实姓名，便于分享人核实" :disabled="joining" />
      <text class="field-label">手机号</text><input v-model="phone" class="input" type="number" maxlength="11" placeholder="填写 11 位手机号" :disabled="joining" />
      <text class="apply-note">分享人同意后，才能进入项目和上传照片。</text>
    </view>
    <view v-if="error" class="error-panel" role="alert">{{ error }}</view>
    <button class="primary-button pressable join-button" :disabled="!canJoin" @tap="joinProject">{{ joinLabel }}</button>
    <button class="return-home pressable" @tap="backHome">返回工作台</button>
  </view>
</template>

<style scoped>
.join-page { padding-bottom: calc(48rpx + var(--safe-bottom)); }
.code-label { margin-top: 0; }
.invite-input { text-transform: uppercase; letter-spacing: 5rpx; }
.input-placeholder { letter-spacing: 0; }
.project-preview { margin-top: 24rpx; padding: 25rpx 22rpx; }
.preview-name { display: block; color: var(--text); font-size: 28rpx; font-weight: 600; line-height: 1.45; }
.preview-meta { display: block; margin-top: 8rpx; color: var(--primary-strong); font-size: 23rpx; }
.preview-loading { display: flex; align-items: center; justify-content: center; gap: 16rpx; min-height: 132rpx; color: var(--muted); font-size: 23rpx; }
.preview-loading .loading-spinner { width: 38rpx; height: 38rpx; margin: 0; border-width: 4rpx; }
.error-panel { margin-top: 22rpx; padding: 18rpx 20rpx; border: 1rpx solid rgba(255, 107, 102, 0.28); border-radius: 18rpx; color: #ffb1b1; background: rgba(255, 107, 102, 0.1); font-size: 23rpx; line-height: 1.5; }
.join-button { margin-top: 28rpx; }
.apply-note { display:block; margin-top:20rpx; color:var(--muted); font-size:24rpx; line-height:1.5; }
.return-home { display:flex; align-items:center; justify-content:center; min-height:44px; margin-top:20rpx; color:var(--muted); background:transparent; font-size:25rpx; }
</style>
