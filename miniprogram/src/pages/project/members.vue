<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { sessionState } from '@/services/auth'
import { canManageProjectMembers, PROJECT_ROLE_LABELS } from '@/services/project-membership'
import { bootstrapState, loadBootstrap } from '@/stores/bootstrap'
import { selectionStorage } from '@/stores/selection'
import type { ProjectAccessRole, ProjectMember, ProjectSummary } from '@/types/domain'

const project = ref<ProjectSummary>(selectionStorage.getProject())
const members = ref<ProjectMember[]>([])
const loading = ref(true)
const changing = ref(false)
const canManage = computed(() => canManageProjectMembers(project.value))

function syncProject(next: ProjectSummary) {
  project.value = next
  selectionStorage.setProject(next)
  bootstrapState.currentProject = next
  const index = bootstrapState.projects.findIndex((item) => item.id === next.id)
  if (index >= 0) bootstrapState.projects.splice(index, 1, next)
}

async function load() {
  project.value = selectionStorage.getProject()
  if (!project.value.id) {
    loading.value = false
    uni.redirectTo({ url: '/pages/project/select' })
    return
  }
  try {
    const response = await mobileApi.projectMembers(project.value.id)
    syncProject(response.project)
    members.value = response.members
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

function openInvite() {
  if (canManage.value) uni.navigateTo({ url: '/pages/project/invite' })
}

function roleChoices(member: ProjectMember): ProjectAccessRole[] {
  if (project.value.access_role === 'owner') return ['admin', 'capturer', 'viewer'].filter((role) => role !== member.role) as ProjectAccessRole[]
  if (member.role === 'owner' || member.role === 'admin') return []
  return ['capturer', 'viewer'].filter((role) => role !== member.role) as ProjectAccessRole[]
}

async function changeMember(member: ProjectMember) {
  if (!canManage.value || changing.value || member.is_me || member.role === 'owner') return
  const roles = roleChoices(member)
  const items = [...roles.map((role) => `设为${PROJECT_ROLE_LABELS[role]}`), '移除成员']
  if (!items.length) return
  uni.showActionSheet({ itemList: items, success: async ({ tapIndex }) => {
    if (changing.value) return
    if (tapIndex === roles.length) {
      uni.showModal({ title: `移除${member.display_name}？`, content: '移除后对方将不能继续查看或上传该工程。', confirmColor: '#ff6b66', success: async ({ confirm }) => {
        if (!confirm) return
        changing.value = true
        try {
          await mobileApi.removeProjectMember(project.value.id, member.account_id)
          await load()
        } catch (error) {
          uni.showToast({ title: error instanceof Error ? error.message : '移除失败', icon: 'none' })
        } finally { changing.value = false }
      } })
      return
    }
    const role = roles[tapIndex]
    if (!role) return
    changing.value = true
    try {
      await mobileApi.updateProjectMember(project.value.id, member.account_id, role)
      await load()
    } catch (error) {
      uni.showToast({ title: error instanceof Error ? error.message : '角色修改失败', icon: 'none' })
    } finally { changing.value = false }
  } })
}

onLoad(load)
onShow(() => { if (!loading.value) void load() })
</script>

<template>
  <view class="page-shell no-tabs members-page">
    <PageHeader title="项目成员" :subtitle="project.name" />
    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">加载中…</text></view>
    <view v-else-if="members.length" class="member-list card">
      <button v-for="member in members" :key="member.account_id" class="member-row pressable" :disabled="!canManage || member.is_me || member.role === 'owner'" @tap="changeMember(member)">
        <view class="member-avatar">{{ (member.display_name || member.username || '成').slice(0, 1) }}</view>
        <view class="member-copy"><text class="member-name">{{ member.display_name || member.username || '成员' }}<text v-if="member.is_me" class="me-label">我</text></text><text class="member-account">{{ member.username }}</text></view>
        <text class="status-chip">{{ PROJECT_ROLE_LABELS[member.role] }}</text>
      </button>
    </view>
    <view v-else class="empty-state"><text class="empty-title">暂无成员</text></view>
    <button v-if="canManage" class="primary-button pressable invite-button" @tap="openInvite">邀请成员</button>
  </view>
</template>

<style scoped>
.members-page { padding-bottom: calc(48rpx + var(--safe-bottom)); }
.member-list { overflow: hidden; }
.member-row { display: grid; grid-template-columns: 72rpx minmax(0, 1fr) auto; align-items: center; gap: 16rpx; width: 100%; min-height: 104rpx; padding: 15rpx 20rpx; border-bottom: 1rpx solid var(--line); text-align: left; background: transparent; }
.member-row:last-child { border-bottom: 0; }
.member-row[disabled] { opacity: 1; }
.member-avatar { display: grid; place-items: center; width: 68rpx; height: 68rpx; border-radius: 21rpx; color: var(--primary-strong); background: var(--primary-soft); font-size: 28rpx; font-weight: 700; }
.member-copy { min-width: 0; }
.member-name { display: block; overflow: hidden; color: var(--text); font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.member-account { display: block; overflow: hidden; margin-top: 5rpx; color: var(--muted); font-size: 21rpx; text-overflow: ellipsis; white-space: nowrap; }
.me-label { margin-left: 10rpx; color: var(--primary-strong); font-size: 20rpx; font-weight: 500; }
.invite-button { margin-top: 26rpx; }
</style>
