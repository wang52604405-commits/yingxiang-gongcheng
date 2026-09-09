<script setup lang="ts">
import { themeStyle } from '@/services/theme'
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
    if (!project.value.id) throw new Error('请先选择或加入工程')
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
}

onLoad(load)
</script>

<template>
  <page-meta :page-style="themeStyle" />
  <view class="page-shell no-tabs requirements-page">
    <PageHeader title="专业采集清单" />
    <scroll-view scroll-x class="filter-scroll">
      <view class="filter-row">
        <button class="filter-chip pressable" :class="{ active: filter === 'all' }" @tap="filter = 'all'">全部 {{ summary.total }}</button>
        <button class="filter-chip pressable required" :class="{ active: filter === 'required' }" @tap="filter = 'required'">必拍 {{ summary.required }}</button>
        <button class="filter-chip pressable conditional" :class="{ active: filter === 'conditional' }" @tap="filter = 'conditional'">条件 {{ summary.conditional }}</button>
        <button class="filter-chip pressable" :class="{ active: filter === 'recommended' }" @tap="filter = 'recommended'">推荐 {{ summary.recommended }}</button>
      </view>
    </scroll-view>
    <input v-model="keyword" class="search-input" placeholder="搜索清单" placeholder-class="input-placeholder" />
    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">加载中…</text></view>
    <view v-else-if="visible.length" class="requirement-list">
      <button v-for="item in visible" :key="item.template_code" class="requirement-card card pressable" @tap="startCapture(item)">
        <view class="requirement-head">
          <text class="requirement-tag" :class="item.required_type">{{ labels[item.required_type] }}</text>
          <text class="requirement-code">{{ item.template_code }}</text>
        </view>
        <text class="requirement-title">{{ item.photo_requirement_name }}</text>
        <text class="requirement-path">{{ [item.phase, item.division, item.subdivision, item.item, item.process].filter(Boolean).join(' / ') }}</text>
        <view class="requirement-footer"><view class="requirement-meta"><text>至少 {{ item.min_photo_count || 1 }} 张</text><text>{{ item.shot_types || '按现场实际' }}</text><text v-if="item.before_concealment_required === '是'">隐蔽前</text></view><text class="capture-label">采集 ›</text></view>
        <text v-if="item.condition" class="condition">适用条件：{{ item.condition }}</text>
      </button>
    </view>
    <view v-else class="empty-state"><text class="empty-title">暂无采集清单</text><text class="empty-copy">可按工程部位直接采集</text></view>
  </view>
</template>

<style scoped>
.requirements-page { padding-bottom: calc(40rpx + var(--safe-bottom)); }
.search-input { height:88rpx; margin-bottom:20rpx; padding:0 22rpx; border:1rpx solid var(--line); border-radius:20rpx; background:var(--surface); color:var(--text); font-size:25rpx; }
.filter-scroll { margin:0 0 16rpx; white-space:nowrap; }
.filter-row { display:flex; gap:12rpx; }
.filter-chip { display:inline-flex; align-items:center; justify-content:center; min-height:40px; padding:8rpx 24rpx; border:1rpx solid var(--line); border-radius:999rpx; background:var(--surface); color:var(--muted); font-size:22rpx; line-height:1.25; text-align:center; }
.filter-chip.active { border-color:var(--primary); background:var(--primary-soft); color:var(--primary-strong); }
.requirement-list { display:grid; gap:18rpx; }
.requirement-card { display:block; width:100%; padding:24rpx; text-align:left; }
.requirement-head { display:flex; align-items:center; justify-content:space-between; min-width:0; gap:16rpx; }
.requirement-tag { flex:0 0 auto; padding:5rpx 12rpx; border-radius:999rpx; background:var(--primary-soft); color:var(--primary-strong); font-size:22rpx; }
.requirement-tag.required { background:rgba(255,95,95,.14); color:#ff7777; }
.requirement-tag.conditional { background:rgba(255,181,71,.14); color:#f0ad4e; }
.requirement-code { max-width:60%; overflow:hidden; color:var(--muted); font-size:22rpx; text-overflow:ellipsis; white-space:nowrap; }
.requirement-title { display:block; margin-top:13rpx; color:var(--text); font-size:27rpx; font-weight:700; }
.requirement-path { display:block; margin-top:8rpx; color:var(--muted); font-size:22rpx; line-height:1.5; }
.requirement-footer { display:flex; align-items:flex-end; justify-content:space-between; gap:16rpx; margin-top:12rpx; }
.requirement-meta { display:flex; flex:1; flex-wrap:wrap; gap:12rpx; color:var(--primary-strong); font-size:22rpx; }
.capture-label { flex:0 0 auto; color:var(--primary-strong); font-size:23rpx; font-weight:600; }
.condition { display:block; margin-top:10rpx; color:var(--muted); font-size:22rpx; line-height:1.5; }
</style>
