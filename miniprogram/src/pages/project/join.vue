<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { sessionState } from '@/services/auth'
import { normalizeInviteCode, consumePendingInvite } from '@/services/pending-invite'
import { PROJECT_ROLE_LABELS } from '@/services/project-membership'
import { applyBootstrap, loadBootstrap } from '@/stores/bootstrap'
import { selectionStorage } from '@/stores/selection'
import type { ProjectInvite } from '@/types/domain'

const code = ref('')
const preview = ref<ProjectInvite | null>(null)
const loading = ref(false)
const joining = ref(false)
const error = ref('')
const canJoin = computed(() => Boolean(preview.value?.project.id) && !loading.value && !joining.value)
const joinLabel = computed(() => joining.value ? '打开中…' : preview.value?.already_joined ? '打开项目' : '加入项目')
let previewTimer: ReturnType<typeof setTimeout> | null = null
let previewVersion = 0

async function loadPreview(expectedCode = code.value) {
  const normalized = normalizeInviteCode(expectedCode)
  if (normalized.length !== 10) return
  const version = ++previewVersion
  loading.value = true
  error.value = ''
  try {
    const response = await mobileApi.previewProjectInvite(normalized)
    if (version === previewVersion && code.value === normalized) preview.value = response.invite
  } catch (reason) {
    if (version === previewVersion) {
      preview.value = null
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
  if (normalized.length === 10) previewTimer = setTimeout(() => { void loadPreview(normalized) }, 220)
})

async function joinProject() {
  const account = sessionState.account
  if (!account || !canJoin.value) return
  joining.value = true
  error.value = ''
  try {
    if (preview.value?.already_joined) {
      await loadBootstrap(account.id, preview.value.project.id)
      uni.reLaunch({ url: '/pages/home/index' })
      return
    }
    const response = await mobileApi.joinProjectInvite(code.value)
    selectionStorage.setProject(response.project)
    if (response.bootstrap) applyBootstrap(account.id, response.bootstrap, response.project.id)
    else await loadBootstrap(account.id, response.project.id)
    uni.showToast({ title: response.idempotent ? '已在该项目中' : '已加入项目', icon: 'success' })
    setTimeout(() => uni.reLaunch({ url: '/pages/home/index' }), 450)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加入项目失败'
  } finally { joining.value = false }
}

onLoad((query) => {
  const pending = consumePendingInvite()
  code.value = normalizeInviteCode(query?.code || query?.invite || pending)
})
</script>

<template>
  <view class="page-shell no-tabs join-page">
    <PageHeader title="加入项目" />
    <text class="field-label code-label">邀请码</text>
    <input v-model="code" class="input invite-input" maxlength="10" type="text" placeholder="输入 10 位邀请码" placeholder-class="input-placeholder" />
    <view v-if="loading" class="preview-loading"><view class="loading-spinner" /><text>正在确认…</text></view>
    <view v-else-if="preview" class="project-preview card">
      <text class="preview-name">{{ preview.project.name }}</text>
      <text class="preview-meta">{{ PROJECT_ROLE_LABELS[preview.role] }}<template v-if="preview.inviter_name"> · {{ preview.inviter_name }}邀请</template></text>
    </view>
    <view v-if="error" class="error-panel" role="alert">{{ error }}</view>
    <button class="primary-button pressable join-button" :disabled="!canJoin" @tap="joinProject">{{ joinLabel }}</button>
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
</style>
