<script setup lang="ts">
import { usePageTheme } from '@/services/theme'
const themeStyle = usePageTheme()
import { computed, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { sessionState } from '@/services/auth'
import { canManageProjectMembers, PROJECT_ROLE_LABELS } from '@/services/project-membership'
import { bootstrapState, loadBootstrap } from '@/stores/bootstrap'
import { selectionStorage } from '@/stores/selection'
import { projectApplicationsApi } from '@/services/project-applications'
import type { ProjectAccessRole, ProjectMember, ProjectSummary } from '@/types/domain'

const project = ref<ProjectSummary>(selectionStorage.getProject())
const members = ref<ProjectMember[]>([])
const loading = ref(true)
const changing = ref(false)
const pendingCount = ref(0)
let loadGeneration = 0
const canManage = computed(() => canManageProjectMembers(project.value))

function syncProject(next: ProjectSummary) {
  project.value = next
  selectionStorage.setProject(next)
  bootstrapState.currentProject = next
  const index = bootstrapState.projects.findIndex((item) => item.id === next.id)
  if (index >= 0) bootstrapState.projects.splice(index, 1, next)
}

async function load() {
  const generation = ++loadGeneration
  const accountId = sessionState.account?.id
  pendingCount.value = 0
  project.value = selectionStorage.getProject()
  if (!project.value.id) {
    loading.value = false
    uni.redirectTo({ url: '/pages/project/select' })
    return
  }
  try {
    const response = await mobileApi.projectMembers(project.value.id)
    if (generation !== loadGeneration || sessionState.account?.id !== accountId) return
    syncProject(response.project)
    members.value = response.members
    if (canManage.value) {
      const projectId = project.value.id
      void projectApplicationsApi.pending(projectId).then((rows) => {
        if (generation === loadGeneration && sessionState.account?.id === accountId && project.value.id === projectId) pendingCount.value = rows.length
      }).catch(() => undefined)
    }
  } catch (error: any) {
    const code = String(error?.code || '').toLowerCase()
    if (['project_access_revoked', 'project_permission_denied', 'project_access_denied', 'project_not_found'].includes(code) && sessionState.account) {
      await loadBootstrap(sessionState.account.id).catch(() => undefined)
      uni.showModal({ title: '已无法访问该工程', content: '工程列表已刷新。', showCancel: false, success: () => uni.navigateBack() })
    } else {
      uni.showToast({ title: error instanceof Error ? error.message : '成员读取失败', icon: 'none' })
    }
  } finally {
    loading.value = false
  }
}

function openWatermarkSettings() { if (canManage.value) uni.navigateTo({ url: '/pages/project/watermark-settings' }) }

function openInvite() {
  if (canManage.value) uni.navigateTo({ url: '/pages/project/invite' })
}

function openApplications() {
  if (canManage.value) uni.navigateTo({ url: '/pages/project/applications' })
}

function roleChoices(member: ProjectMember): ProjectAccessRole[] {
  if (project.value.access_role === 'owner') return ['admin', 'capturer', 'viewer'].filter((role) => role !== member.role) as ProjectAccessRole[]
  if (member.role === 'owner' || member.role === 'admin') return []
  return ['capturer', 'viewer'].filter((role) => role !== member.role) as ProjectAccessRole[]
}

function canChangeRole(member: ProjectMember): boolean {
  return canManage.value && !changing.value && !member.is_me && member.role !== 'owner' && roleChoices(member).length > 0
}

async function changeMember(member: ProjectMember) {
  if (!canChangeRole(member)) return
  const roles = roleChoices(member)
  const items = roles.map((role) => `设为${PROJECT_ROLE_LABELS[role]}`)
  if (!items.length) return
  uni.showActionSheet({ itemList: items, success: async ({ tapIndex }) => {
    if (changing.value) return
    const role = roles[tapIndex]
    if (!role) return
    changing.value = true
    try {
      await mobileApi.updateProjectMember(project.value.id, member.account_id, role)
      uni.showToast({ title: `已设为${PROJECT_ROLE_LABELS[role]}`, icon: 'none' })
      await load()
    } catch (error) {
      uni.showToast({ title: error instanceof Error ? error.message : '角色修改失败', icon: 'none' })
    } finally { changing.value = false }
  } })
}

function memberName(member: ProjectMember): string {
  return member.display_name || (/^wx_/i.test(member.username || '') ? '微信成员' : member.username) || '成员'
}

function memberSubtitle(member: ProjectMember): string {
  return /^wx_/i.test(member.username || '') ? PROJECT_ROLE_LABELS[member.role] : (member.username || PROJECT_ROLE_LABELS[member.role])
}

async function removeMember(member: ProjectMember) {
  if (project.value.access_role !== 'owner' || changing.value || member.is_me || member.role === 'owner') return
  changing.value = true
  const projectId = project.value.id
  const accountId = sessionState.account?.id
  try {
    const confirmed = await new Promise<boolean>((resolve) => uni.showModal({
      title: `确定将${memberName(member)}移出项目？`,
      content: '已有照片会保留。删除成员后，对方将失去本项目的查看和上传权限。',
      confirmText: '删除',
      confirmColor: '#b52e28',
      success: ({ confirm }) => resolve(Boolean(confirm)),
      fail: () => resolve(false),
    }))
    if (!confirmed || sessionState.account?.id !== accountId || selectionStorage.getProject().id !== projectId) return
    await mobileApi.removeProjectMember(projectId, member.account_id)
    if (sessionState.account?.id !== accountId) return
    uni.showToast({ title: '成员已删除', icon: 'none' })
    await load()
  } catch (error) {
    uni.showToast({ title: error instanceof Error ? error.message : '删除成员失败，请重试', icon: 'none' })
  } finally { changing.value = false }
}

onLoad(load)
onShow(() => { if (!loading.value) void load() })
</script>

<template>
  <page-meta :page-style="themeStyle" />
  <view class="page-shell no-tabs members-page" :style="themeStyle">
    <PageHeader title="项目成员" :subtitle="project.name" />
    <button v-if="canManage" class="application-entry card pressable" @tap="openApplications">
      <text>加入申请</text>
      <view class="application-entry-trailing">
        <text v-if="pendingCount" class="application-count">{{ pendingCount }} 人待审核</text>
        <text v-else>查看</text>
        <text>›</text>
      </view>
    </button>
    <button v-if="canManage" class="application-entry card pressable" @tap="openWatermarkSettings">
      <text>图标与施工单位</text>
      <view class="application-entry-trailing"><text>统一设置</text><text>›</text></view>
    </button>
    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">加载中…</text></view>
    <view v-else-if="members.length" class="member-list card">
      <view v-for="member in members" :key="member.account_id" class="member-row">
        <view class="member-main">
          <view class="member-avatar">{{ memberName(member).slice(0, 1) }}</view>
          <view class="member-copy">
            <text class="member-name">{{ memberName(member) }}<text v-if="member.is_me" class="me-label">我</text></text>
            <text class="member-account">{{ memberSubtitle(member) }}</text>
          </view>
        </view>
        <button
          class="status-chip member-role"
          :class="{ 'role-editable': canChangeRole(member) }"
          :disabled="!canChangeRole(member)"
          @tap.stop="changeMember(member)"
        >
          <text>{{ PROJECT_ROLE_LABELS[member.role] }}</text>
          <text v-if="canChangeRole(member)" class="role-chevron">⌄</text>
        </button>
        <button
          v-if="project.access_role === 'owner' && !member.is_me && member.role !== 'owner'"
          class="remove-member pressable"
          :disabled="changing"
          @tap.stop="removeMember(member)"
        >删除</button>
      </view>
    </view>
    <view v-else class="empty-state"><text class="empty-title">暂无成员</text></view>
    <text v-if="project.access_role === 'owner' && members.length" class="role-tip">点击成员角色可设为管理员、采集员或只读。</text>
    <button v-if="canManage" class="primary-button pressable invite-button" @tap="openInvite">邀请成员</button>
  </view>
</template>

<style scoped>
.members-page { padding-bottom: calc(48rpx + var(--safe-bottom)); }
.application-entry { display: flex; justify-content: space-between; align-items: center; width: 100%; min-height: 94rpx; margin-bottom: 22rpx; padding: 20rpx 24rpx; color: var(--text); font-size: 28rpx; text-align: left; }
.application-entry-trailing { display: flex; align-items: center; gap: 16rpx; color: var(--muted); font-size: 24rpx; }
.application-count { color: var(--primary-strong); }
.member-list { overflow: hidden; }
.member-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 12rpx; min-height: 116rpx; padding: 12rpx 18rpx; border-bottom: 1rpx solid var(--line); background: var(--surface); }
.member-row:last-child { border-bottom: 0; }
.member-main { display: grid; grid-template-columns: 72rpx minmax(0, 1fr); align-items: center; gap: 16rpx; width: 100%; min-width: 0; min-height: 88rpx; color: var(--text); text-align: left; }
.member-avatar { display: grid; place-items: center; width: 68rpx; height: 68rpx; border-radius: 21rpx; color: var(--primary-strong); background: var(--primary-soft); font-size: 28rpx; font-weight: 700; }
.member-copy { min-width: 0; }
.member-name { display: block; overflow: hidden; color: var(--text); font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.member-account { display: block; overflow: hidden; margin-top: 5rpx; color: var(--muted); font-size: 21rpx; text-overflow: ellipsis; white-space: nowrap; }
.me-label { margin-left: 10rpx; color: var(--primary-strong); font-size: 20rpx; font-weight: 500; }
.member-role { display: flex; align-items: center; justify-content: center; justify-self: end; min-height: 52rpx; margin: 0; padding: 0 14rpx; border: 1rpx solid transparent; font-size: 21rpx; line-height: 1; }
.member-role[disabled] { opacity: 1; }
.member-role.role-editable { border-color: rgba(32, 132, 121, .28); color: var(--primary-strong); background: var(--primary-soft); }
.role-chevron { margin-left: 7rpx; font-size: 20rpx; transform: translateY(-2rpx); }
.remove-member { display: flex; align-items: center; justify-content: center; min-width: 76rpx; min-height: 64rpx; padding: 0 8rpx 0 16rpx; border-left: 1rpx solid var(--line); border-radius: 0; color: var(--danger); background: transparent; font-size: 23rpx; font-weight: 600; line-height: 1; }
.remove-member[disabled] { opacity: 0.45; }
.role-tip { display: block; margin: 14rpx 6rpx 0; color: var(--muted); font-size: 21rpx; line-height: 1.5; }
.invite-button { margin-top: 26rpx; }
</style>
