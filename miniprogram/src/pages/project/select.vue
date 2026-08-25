<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { CURRENT_PROJECT } from '@/config/env'
import { selectionStorage } from '@/stores/selection'
import { bootstrapState } from '@/stores/bootstrap'
import type { ProjectSummary } from '@/types/domain'

const projects = ref<ProjectSummary[]>([...bootstrapState.projects])
const loading = ref(!projects.value.length)
const current = ref(selectionStorage.getProject())

async function load() {
  try {
    const response = await mobileApi.projects()
    projects.value = response.projects?.length ? response.projects : [{ ...CURRENT_PROJECT, unit_count: 888 }]
  } catch {
    if (!projects.value.length) projects.value = [{ ...CURRENT_PROJECT, unit_count: 888 }]
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
    <view v-else class="project-list">
      <button v-for="project in projects" :key="project.id" class="project-card card pressable" :class="{ active: current.id === project.id }" @tap="select(project)">
        <view class="project-symbol">水</view>
        <view class="project-copy"><text class="project-name">{{ project.name }}</text><text class="project-meta">{{ project.code }} · {{ project.unit_count || 0 }} 个单元</text></view>
        <text class="check">{{ current.id === project.id ? '✓' : '›' }}</text>
      </button>
    </view>
  </view>
</template>

<style scoped>
.project-list { display: grid; gap: 18rpx; }
.project-card { display: grid; grid-template-columns: 82rpx 1fr 40rpx; align-items: center; gap: 18rpx; width: 100%; padding: 22rpx; text-align: left; }
.project-card.active { border-color: var(--primary); background: var(--primary-soft); }
.project-symbol { display: grid; place-items: center; width: 78rpx; height: 78rpx; border-radius: 23rpx; color: var(--primary-strong); background: var(--primary-soft); font-size: 31rpx; font-weight: 700; }
.project-copy { min-width: 0; }
.project-name { display: block; color: var(--text); font-size: 28rpx; font-weight: 650; line-height: 1.45; }
.project-meta { display: block; margin-top: 7rpx; color: var(--muted); font-size: 21rpx; }
.check { color: var(--primary-strong); text-align: center; font-size: 34rpx; }
</style>
