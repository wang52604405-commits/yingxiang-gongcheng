<script setup lang="ts">
import { themeStyle } from '@/services/theme'
import { computed, ref } from 'vue'
import { onLoad, onShareAppMessage } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { canManageProjectMembers, PROJECT_ROLE_LABELS } from '@/services/project-membership'
import { selectionStorage } from '@/stores/selection'
import type { ProjectAccessRole, ProjectInvite, ProjectSummary } from '@/types/domain'

const project = ref<ProjectSummary>(selectionStorage.getProject())
const role = ref<ProjectAccessRole>('capturer')
const invite = ref<ProjectInvite | null>(null)
const creating = ref(false)
const allowedRoles = computed<ProjectAccessRole[]>(() => project.value.access_role === 'owner' ? ['admin', 'capturer', 'viewer'] : ['capturer', 'viewer'])
const displayCode = computed(() => invite.value?.code ? `${invite.value.code.slice(0, 5)} ${invite.value.code.slice(5)}` : '')

function chooseRole(next: ProjectAccessRole) {
  if (!allowedRoles.value.includes(next) || creating.value) return
  role.value = next
  invite.value = null
}

async function createInvite() {
  if (!project.value.id || !canManageProjectMembers(project.value) || creating.value) return
  creating.value = true
  try {
    const response = await mobileApi.createProjectInvite(project.value.id, role.value)
    invite.value = response.invite
  } catch (error) {
    uni.showToast({ title: error instanceof Error ? error.message : '邀请生成失败', icon: 'none' })
  } finally { creating.value = false }
}

function copyCode() {
  if (!invite.value?.code) return
  uni.setClipboardData({ data: invite.value.code, success: () => uni.showToast({ title: '邀请码已复制', icon: 'success' }) })
}

onShareAppMessage(() => ({
  title: `邀请你加入${invite.value?.project.name || project.value.name}`,
  path: `/pages/project/join?code=${encodeURIComponent(invite.value?.code || '')}`,
}))

onLoad(() => {
  project.value = selectionStorage.getProject()
  if (!project.value.id || !canManageProjectMembers(project.value)) {
    uni.showModal({ title: '无法邀请成员', content: '当前账号没有成员管理权限。', showCancel: false, success: () => uni.navigateBack() })
  }
})
</script>

<template>
  <page-meta :page-style="themeStyle" />
  <view class="page-shell no-tabs invite-page">
    <PageHeader title="邀请成员" :subtitle="project.name" />
    <template v-if="!invite">
      <text class="field-label role-label">审批通过后的角色</text>
      <view class="role-list card">
        <button v-for="item in allowedRoles" :key="item" class="role-row pressable" :class="{ active: role === item }" @tap="chooseRole(item)"><text>{{ PROJECT_ROLE_LABELS[item] }}</text><text class="role-check">{{ role === item ? '✓' : '' }}</text></button>
      </view>
      <button class="primary-button pressable create-button" :disabled="creating" @tap="createInvite">{{ creating ? '生成中…' : '生成邀请' }}</button>
    </template>
    <template v-else>
      <view class="invite-card card">
        <text class="invite-project">{{ invite.project.name }}</text>
        <text class="invite-code">{{ displayCode }}</text>
        <text class="invite-meta">需审批 · {{ PROJECT_ROLE_LABELS[invite.role] }}<template v-if="invite.expires_at"> · 短期有效</template></text>
      </view>
      <button class="primary-button pressable share-button" open-type="share">发给微信好友</button>
      <button class="copy-button pressable" @tap="copyCode">复制邀请码</button>
    </template>
  </view>
</template>

<style scoped>
.invite-page { padding-bottom: calc(48rpx + var(--safe-bottom)); }
.role-label { margin-top: 0; }
.role-list { overflow: hidden; }
.role-row { display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 92rpx; padding: 0 22rpx; border-bottom: 1rpx solid var(--line); color: var(--text); text-align: left; background: transparent; font-size: 27rpx; }
.role-row:last-child { border-bottom: 0; }
.role-row.active { color: var(--primary-strong); background: var(--primary-soft); }
.role-check { font-size: 30rpx; }
.create-button, .share-button { margin-top: 28rpx; }
.invite-card { padding: 34rpx 24rpx; text-align: center; }
.invite-project { display: block; overflow: hidden; color: var(--text); font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.invite-code { display: block; margin-top: 28rpx; color: var(--primary-strong); font-size: 48rpx; font-weight: 700; letter-spacing: 5rpx; }
.invite-meta { display: block; margin-top: 18rpx; color: var(--muted); font-size: 22rpx; }
.copy-button { display: flex; align-items: center; justify-content: center; min-height: 40px; margin: 16rpx auto 0; padding: 0 22rpx; color: var(--primary-strong); font-size: 24rpx; }
</style>
