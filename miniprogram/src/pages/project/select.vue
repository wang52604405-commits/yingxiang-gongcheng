<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { selectionStorage } from '@/stores/selection'
import { bootstrapState } from '@/stores/bootstrap'
import type { ProjectSummary } from '@/types/domain'

const projects = ref<ProjectSummary[]>([...bootstrapState.projects])
const loading = ref(!projects.value.length)
const current = ref(selectionStorage.getProject())

async function load() {
  try {
    const response = await mobileApi.projects()
    projects.value = response.projects || []
  } catch {
    uni.showToast({ title: '工程列表读取失败，请检查网络', icon: 'none' })
  } finally {
    loading.value = false
  }
}

function select(project: ProjectSummary) {
  selectionStorage.setProject(project)
  bootstrapState.currentProject = project
  current.value = project
  uni.showToast({ title: '工程已切换', icon: 'success' })
  setTimeout(() => uni.navigateBack(), 250)
}

onLoad(load)
</script>

<template>
  <view class="page-shell no-tabs">
    <PageHeader title="选择工程" subtitle="服务器同步的工程项目" />
    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">正在读取工程</text></view>
    <view v-else-if="projects.length" class="project-list card">
      <button v-for="project in projects" :key="project.id" class="project-card pressable" :class="{ active: current.id === project.id }" @tap="select(project)">
        <view class="project-symbol">{{ project.industry?.includes('房') ? '建' : project.industry?.includes('市政') ? '市' : project.industry?.includes('电') ? '电' : project.industry?.includes('水') ? '水' : '工' }}</view>
        <view class="project-copy"><text class="project-name">{{ project.name }}</text><text class="project-meta">{{ project.industry || '水利工程' }} · {{ project.project_type || project.code }} · {{ project.unit_count || 0 }} 个工程部位</text></view>
        <text class="check">{{ current.id === project.id ? '✓' : '›' }}</text>
      </button>
    </view>
    <view v-else class="empty-state"><text class="empty-title">这个账号还没有工程</text><text class="empty-copy">请先在原电脑登录同一账号并同步工程，手机会自动拉取真实工程数据。</text></view>
  </view>
</template>

<style scoped>
.project-list { display: grid; gap: 0; overflow: hidden; }
.project-card { display: grid; grid-template-columns: 82rpx minmax(0, 1fr) 40rpx; align-items: center; gap: 18rpx; width: 100%; padding: 22rpx; border-bottom: 1rpx solid var(--line); text-align: left; background: transparent; }
.project-card:last-child { border-bottom: 0; }
.project-card.active { background: var(--primary-soft); }
.project-symbol { display: grid; place-items: center; width: 78rpx; height: 78rpx; border-radius: 23rpx; color: var(--primary-strong); background: var(--primary-soft); font-size: 31rpx; font-weight: 700; }
.project-copy { min-width: 0; }
.project-name { display: block; color: var(--text); font-size: 28rpx; font-weight: 600; line-height: 1.45; }
.project-meta { display: block; margin-top: 7rpx; color: var(--muted); font-size: 21rpx; }
.check { display: grid; place-items: center; width: 40rpx; height: 48rpx; color: var(--primary-strong); text-align: center; font-size: 34rpx; line-height: 1; }
</style>
