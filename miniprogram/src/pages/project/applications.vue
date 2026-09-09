<script setup lang="ts">
import { usePageTheme } from '@/services/theme'
const themeStyle = usePageTheme()
import { computed, ref } from 'vue'
import { onLoad, onShow, onPullDownRefresh } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { selectionStorage } from '@/stores/selection'
import { sessionState } from '@/services/auth'
import { canManageProjectMembers } from '@/services/project-membership'
import { projectApplicationsApi, type ReviewableProjectApplication } from '@/services/project-applications'

const project = ref(selectionStorage.getProject())
const applications = ref<ReviewableProjectApplication[]>([])
const loading = ref(true)
const error = ref('')
const busyId = ref('')
const rejectId = ref('')
let generation = 0
let loaded = false
const canManage = computed(() => canManageProjectMembers(project.value))

async function load() {
  const current = ++generation
  const accountId = sessionState.account?.id
  project.value = selectionStorage.getProject()
  applications.value = []
  error.value = ''
  loading.value = true
  rejectId.value = ''
  try {
    if (!canManage.value) { error.value = '当前账号没有审核权限'; return }
    const rows = await projectApplicationsApi.pending(project.value.id)
    if (current !== generation || sessionState.account?.id !== accountId) return
    applications.value = rows
  } catch (caught) {
    if (current === generation) error.value = caught instanceof Error ? caught.message : '申请读取失败，请重试'
  } finally {
    if (current === generation) { loading.value = false; loaded = true }
    uni.stopPullDownRefresh()
  }
}

async function review(application: ReviewableProjectApplication, decision: 'approve' | 'reject') {
  if (busyId.value || !canManage.value || !application.can_review) return
  busyId.value = String(application.id)
  const accountId = sessionState.account?.id
  const projectId = project.value.id
  try {
    await projectApplicationsApi.review(application, decision)
    if (sessionState.account?.id !== accountId || selectionStorage.getProject().id !== projectId) return
    applications.value = applications.value.filter((row) => row.id !== application.id)
    rejectId.value = ''
    uni.showToast({ title: decision === 'approve' ? '已同意加入' : '已拒绝申请', icon: 'none' })
  } catch (caught) {
    if (sessionState.account?.id !== accountId) return
    uni.showToast({ title: caught instanceof Error ? caught.message : '处理失败，请重试', icon: 'none' })
    await load()
  } finally { busyId.value = '' }
}

function dateLabel(value: string) { return String(value || '').replace('T', ' ').slice(0, 16) }
onLoad(() => { void load() })
onShow(() => { if (loaded && !busyId.value) void load() })
onPullDownRefresh(() => { if (!busyId.value) void load(); else uni.stopPullDownRefresh() })
</script>

<template>
  <page-meta :page-style="themeStyle" />
  <view class="page-shell no-tabs applications-page" :style="themeStyle">
    <PageHeader title="加入申请" :subtitle="project.name" />
    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">正在读取申请…</text></view>
    <view v-else-if="error" class="empty-state"><text class="empty-title">暂时无法读取</text><text class="empty-copy">{{ error }}</text><button class="secondary-button pressable" @tap="load">重新读取</button></view>
    <template v-else>
      <view class="list-heading"><text>{{ applications.length ? `${applications.length} 人待审核` : '待审核' }}</text><button class="refresh-button pressable" :disabled="!!busyId" @tap="load">刷新</button></view>
      <view v-if="!applications.length" class="empty-state"><text class="empty-title">没有待处理的申请</text><text class="empty-copy">通过你分享的邀请提交申请后，会显示在这里。</text></view>
      <view v-for="application in applications" :key="application.id" class="application-card card">
        <view class="identity-row"><view class="avatar">{{ (application.display_name || '申').slice(0, 1) }}</view><view class="identity"><text class="applicant-name">{{ application.display_name }}</text><text class="phone">{{ application.phone }}</text></view><text class="status-chip">待审核</text></view>
        <text class="submitted">{{ dateLabel(application.created_at) }} 提交</text>
        <view v-if="rejectId === String(application.id)" class="reject-confirm"><text>拒绝后，对方将不能加入该工程。</text><view class="action-row"><button class="secondary-button pressable" :disabled="!!busyId" @tap="rejectId = ''">取消</button><button class="reject-button pressable" :disabled="!!busyId" @tap="review(application, 'reject')">{{ busyId === String(application.id) ? '处理中…' : '确认拒绝' }}</button></view></view>
        <view v-else class="action-row"><button class="secondary-button pressable" :disabled="!!busyId" @tap="rejectId = String(application.id)">拒绝</button><button class="primary-button pressable" :disabled="!!busyId" @tap="review(application, 'approve')">{{ busyId === String(application.id) ? '处理中…' : '同意加入' }}</button></view>
      </view>
    </template>
  </view>
</template>

<style scoped>
.applications-page { padding-bottom: calc(48rpx + var(--safe-bottom)); }
.list-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; color: var(--muted); font-size: 24rpx; }
.refresh-button { margin: 0; padding: 12rpx 20rpx; background: transparent; color: var(--primary-strong); font-size: 25rpx; }
.application-card { padding: 26rpx; margin-bottom: 22rpx; }
.identity-row { display: flex; align-items: center; gap: 18rpx; }
.avatar { display: grid; place-items: center; flex-shrink: 0; width: 76rpx; height: 76rpx; border-radius: 22rpx; background: var(--primary-soft); color: var(--primary-strong); font-size: 30rpx; font-weight: 700; }
.identity { flex: 1; min-width: 0; }
.applicant-name { display: block; color: var(--text); font-size: 31rpx; font-weight: 600; overflow-wrap: anywhere; }
.phone { display: block; margin-top: 7rpx; color: var(--muted); font-size: 27rpx; font-variant-numeric: tabular-nums; }
.submitted { display: block; margin: 22rpx 0; color: var(--muted); font-size: 22rpx; }
.action-row { display: grid; grid-template-columns: 1fr 1.4fr; gap: 18rpx; }
.action-row button { width: 100%; min-height: 84rpx; margin: 0; }
.reject-confirm { color: var(--muted); font-size: 25rpx; }
.reject-confirm .action-row { margin-top: 20rpx; }
.reject-button { color: #ff9188; background: rgba(255, 107, 102, .12); border: 1rpx solid rgba(255, 107, 102, .3); border-radius: 20rpx; font-size: 28rpx; }
</style>
