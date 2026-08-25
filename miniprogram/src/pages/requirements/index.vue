<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import { mobileApi } from '@/api/mobile'
import { launchCapture } from '@/services/capture-entry'
import { selectionStorage } from '@/stores/selection'
import type { PhotoRequirement, ProjectSummary } from '@/types/domain'

const project = ref<ProjectSummary>(selectionStorage.getProject())
const requirements = ref<PhotoRequirement[]>([])
const loading = ref(true)
const filter = ref<'all' | 'required' | 'conditional' | 'recommended'>('all')
const summary = ref({ total: 0, required: 0, conditional: 0, recommended: 0 })
const keyword = ref('')

const labels = { required: '必拍', conditional: '条件必拍', recommended: '推荐' }
const visible = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return requirements.value.filter((item) => {
    if (filter.value !== 'all' && item.required_type !== filter.value) return false
    if (!q) return true
    return `${item.phase} ${item.division} ${item.subdivision || ''} ${item.item || ''} ${item.process || ''} ${item.photo_requirement_name}`.toLowerCase().includes(q)
  })
})

async function load() {
  loading.value = true
  try {
    if (!project.value.id) throw new Error('当前账号尚未从电脑同步工程')
    const response = await mobileApi.projectRequirements(project.value.id)
    project.value = response.project
    summary.value = response.summary
    requirements.value = response.requirements
  } catch (error) {
    uni.showModal({ title: '采集清单读取失败', content: error instanceof Error ? error.message : '请检查网络后重试', showCancel: false })
  } finally {
    loading.value = false
  }
}

function startCapture(item: PhotoRequirement) {
  uni.showModal({
    title: item.photo_requirement_name,
    content: `拍摄时机：${item.timing || '对应工序施工时'}\n拍摄角度：${item.shot_types || '全景/中景/近景'}\n最少：${item.min_photo_count || 1} 张${item.before_concealment_required === '是' ? '\n注意：隐蔽前必须拍摄。' : ''}`,
    confirmText: '采集影像',
    success: ({ confirm }) => {
      if (!confirm) return
      void launchCapture({
        scope: 'engineering',
        category: 'construction',
        mode: 'auto',
        requirement: {
          template_code: item.template_code,
          photo_requirement_name: item.photo_requirement_name,
          required_type: item.required_type,
          min_photo_count: item.min_photo_count,
          timing: item.timing,
          shot_types: item.shot_types,
        },
      })
    },
  })
}

onLoad(load)
</script>

<template>
  <view class="page-shell no-tabs requirements-page">
    <PageHeader title="专业采集清单" :subtitle="`${project.industry || '工程'} · ${project.project_type || project.name}`" />
    <view class="summary-grid">
      <view class="summary-card"><text class="summary-number">{{ summary.total }}</text><text>全部</text></view>
      <view class="summary-card"><text class="summary-number">{{ summary.required }}</text><text>必拍</text></view>
      <view class="summary-card"><text class="summary-number">{{ summary.conditional }}</text><text>条件</text></view>
      <view class="summary-card"><text class="summary-number">{{ summary.recommended }}</text><text>推荐</text></view>
    </view>
    <input v-model="keyword" class="search-input" placeholder="搜索阶段、分部、工序或照片要求" placeholder-class="input-placeholder" />
    <scroll-view scroll-x class="filter-scroll">
      <view class="filter-row">
        <button class="filter-chip" :class="{ active: filter === 'all' }" @tap="filter = 'all'">全部</button>
        <button class="filter-chip required" :class="{ active: filter === 'required' }" @tap="filter = 'required'">必拍</button>
        <button class="filter-chip conditional" :class="{ active: filter === 'conditional' }" @tap="filter = 'conditional'">条件必拍</button>
        <button class="filter-chip" :class="{ active: filter === 'recommended' }" @tap="filter = 'recommended'">推荐</button>
      </view>
    </scroll-view>
    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">正在读取专业模板</text></view>
    <view v-else-if="visible.length" class="requirement-list">
      <button v-for="item in visible" :key="item.template_code" class="requirement-card card pressable" @tap="startCapture(item)">
        <view class="requirement-head">
          <text class="requirement-tag" :class="item.required_type">{{ labels[item.required_type] }}</text>
          <text class="requirement-code">{{ item.template_code }}</text>
        </view>
        <text class="requirement-title">{{ item.photo_requirement_name }}</text>
        <text class="requirement-path">{{ [item.phase, item.division, item.subdivision, item.item, item.process].filter(Boolean).join(' / ') }}</text>
        <view class="requirement-meta"><text>至少 {{ item.min_photo_count || 1 }} 张</text><text>{{ item.shot_types || '按现场实际' }}</text><text v-if="item.before_concealment_required === '是'">隐蔽前</text></view>
        <text v-if="item.condition" class="condition">适用条件：{{ item.condition }}</text>
      </button>
    </view>
    <view v-else class="empty-state"><text class="empty-title">当前项目暂无专业模板清单</text><text class="empty-copy">水利项目继续按桌面端现有项目划分拍摄；房建、市政、电力在桌面端选择专业和工程类型后会自动同步清单。</text></view>
  </view>
</template>

<style scoped>
.requirements-page { padding-bottom: calc(40rpx + var(--safe-bottom)); }
.summary-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12rpx; margin:18rpx 0 20rpx; }
.summary-card { display:flex; flex-direction:column; align-items:center; gap:4rpx; padding:18rpx 8rpx; border:1rpx solid var(--line); border-radius:20rpx; background:var(--surface); color:var(--muted); font-size:19rpx; }
.summary-number { color:var(--text); font-size:30rpx; font-weight:750; }
.search-input { height:82rpx; padding:0 22rpx; border:1rpx solid var(--line); border-radius:20rpx; background:var(--surface); color:var(--text); font-size:24rpx; }
.filter-scroll { margin:18rpx 0; white-space:nowrap; }
.filter-row { display:flex; gap:12rpx; }
.filter-chip { padding:12rpx 22rpx; border:1rpx solid var(--line); border-radius:999rpx; background:var(--surface); color:var(--muted); font-size:21rpx; }
.filter-chip.active { border-color:var(--primary); background:var(--primary-soft); color:var(--primary-strong); }
.requirement-list { display:grid; gap:14rpx; }
.requirement-card { width:100%; padding:20rpx; text-align:left; }
.requirement-head { display:flex; align-items:center; justify-content:space-between; }
.requirement-tag { padding:5rpx 12rpx; border-radius:999rpx; background:var(--primary-soft); color:var(--primary-strong); font-size:19rpx; }
.requirement-tag.required { background:rgba(255,95,95,.14); color:#ff7777; }
.requirement-tag.conditional { background:rgba(255,181,71,.14); color:#f0ad4e; }
.requirement-code { color:var(--muted); font-size:18rpx; }
.requirement-title { display:block; margin-top:13rpx; color:var(--text); font-size:27rpx; font-weight:700; }
.requirement-path { display:block; margin-top:8rpx; color:var(--muted); font-size:20rpx; line-height:1.5; }
.requirement-meta { display:flex; flex-wrap:wrap; gap:12rpx; margin-top:12rpx; color:var(--primary-strong); font-size:19rpx; }
.condition { display:block; margin-top:10rpx; color:var(--muted); font-size:19rpx; line-height:1.5; }
</style>
