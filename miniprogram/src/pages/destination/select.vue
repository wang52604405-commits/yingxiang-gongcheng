<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import UiIcon from '@/components/UiIcon.vue'
import { mobileApi } from '@/api/mobile'
import { selectionStorage } from '@/stores/selection'
import type { ProjectNode, Scope } from '@/types/domain'

const scope = ref<Scope>('engineering')
const keyword = ref('')
const loading = ref(true)
const roots = ref<ProjectNode[]>([])
const selectedNode = ref<ProjectNode | null>(null)

function flatten(nodes: ProjectNode[], parents: string[] = []): Array<ProjectNode & { pathLabel: string }> {
  return nodes.flatMap((node) => {
    const path = [...parents, node.name]
    const current = { ...node, pathLabel: parents.slice(-2).join(' / ') }
    return [current, ...flatten(node.children || [], path)]
  })
}

const selectable = computed(() => {
  const wantedType = scope.value === 'engineering' ? 'unit' : 'other'
  const all = flatten(roots.value).filter((node) => {
    if (scope.value === 'engineering') return node.type === wantedType
    return node.type === wantedType && (!node.children || node.children.length === 0)
  })
  const query = keyword.value.trim().toLowerCase()
  if (!query) return all
  return all.filter((node) => `${node.name} ${node.code} ${node.pathLabel}`.toLowerCase().includes(query))
})

async function loadTree() {
  loading.value = true
  try {
    const project = selectionStorage.getProject()
    if (!project.id) throw new Error('请先选择或加入工程')
    const response = scope.value === 'engineering' ? await mobileApi.projectTree(project.id) : await mobileApi.otherTree(project.id)
    roots.value = response.nodes || []
  } catch (error) {
    uni.showModal({ title: '工程层级读取失败', content: error instanceof Error ? error.message : '请稍后重试', showCancel: false })
  } finally {
    loading.value = false
  }
}

function chooseNode(node: ProjectNode) {
  selectedNode.value = node
  if (scope.value === 'other') saveSelection()
}

function saveSelection(processName = '') {
  const node = selectedNode.value
  if (!node) return
  selectionStorage.setDestination({
    scope: scope.value,
    assignment: scope.value === 'engineering'
      ? { unit_code: node.code, unit_name: node.name, process_name: processName }
      : { other_node_code: node.code, other_node_name: node.name },
  })
  uni.navigateBack()
}

onLoad((query) => {
  scope.value = query?.scope === 'other' ? 'other' : 'engineering'
  void loadTree()
})
</script>

<template>
  <view class="page-shell no-tabs destination-page" :class="{ 'has-process-sheet': scope === 'engineering' && selectedNode }">
    <PageHeader :title="scope === 'engineering' ? '选择工程部位' : '选择其它影像目录'" />
    <view class="search-box"><UiIcon class="search-icon" name="search" :size="19" /><input v-model="keyword" placeholder="搜索名称或编码" placeholder-class="input-placeholder" /></view>

    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">加载中…</text></view>
    <view v-else-if="selectable.length" class="node-list card">
      <button v-for="node in selectable" :key="node.code" class="node-card pressable" :class="{ active: selectedNode?.code === node.code }" @tap="chooseNode(node)">
        <view class="node-copy"><text class="node-name">{{ node.name }}</text><text class="node-path">{{ node.pathLabel || '工程根目录' }}</text><text class="node-code">{{ node.code }}</text></view>
        <text class="node-arrow">{{ selectedNode?.code === node.code ? '✓' : '›' }}</text>
      </button>
    </view>
    <view v-else class="empty-state"><view class="empty-symbol"><UiIcon name="search" :size="27" /></view><text class="empty-title">{{ scope === 'engineering' ? '未找到相关部位' : '未找到相关目录' }}</text></view>

    <view v-if="scope === 'engineering' && selectedNode" class="process-sheet">
      <view class="sheet-handle" />
      <view class="process-head"><text class="process-title">选择工序</text><text class="process-unit">{{ selectedNode.name }}</text></view>
      <scroll-view scroll-x class="process-scroll">
        <view class="process-row">
          <button class="process-chip pressable" @tap="saveSelection('')">不选工序</button>
          <button v-for="process in selectedNode.processes || []" :key="process" class="process-chip pressable" @tap="saveSelection(process)">{{ process }}</button>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<style scoped>
.destination-page { padding-bottom: calc(40rpx + var(--safe-bottom)); }
.destination-page.has-process-sheet { padding-bottom: calc(250rpx + var(--safe-bottom)); }
.search-box { display: grid; grid-template-columns: 48rpx 1fr; align-items: center; gap: 8rpx; height: 86rpx; margin-bottom: 22rpx; padding: 0 22rpx; border: 1rpx solid var(--line); border-radius: 22rpx; background: var(--surface); }
.search-icon { color: var(--primary-strong); font-size: 31rpx; }
.search-box input { width: 100%; color: var(--text); font-size: 26rpx; }
.node-list { display: grid; gap: 0; overflow: hidden; }
.node-card { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 22rpx 24rpx; border-bottom: 1rpx solid var(--line); text-align: left; background: transparent; }
.node-card:last-child { border-bottom: 0; }
.node-card.active { background: var(--primary-soft); }
.node-copy { min-width: 0; }
.node-name { display: block; color: var(--text); font-size: 27rpx; font-weight: 600; }
.node-path { display: block; overflow: hidden; margin-top: 7rpx; color: var(--muted); font-size: 20rpx; text-overflow: ellipsis; white-space: nowrap; }
.node-code { display: block; margin-top: 5rpx; color: var(--primary-strong); font-size: 20rpx; }
.node-arrow { display: grid; flex: 0 0 auto; place-items: center; width: 40rpx; height: 48rpx; margin-left: 16rpx; color: var(--primary-strong); font-size: 35rpx; line-height: 1; text-align: center; }
.process-sheet { position: fixed; z-index: 35; left: 0; right: 0; bottom: 0; padding: 12rpx 28rpx calc(26rpx + env(safe-area-inset-bottom)); border-radius: 34rpx 34rpx 0 0; background: var(--surface); box-shadow: 0 -18rpx 60rpx rgba(0, 0, 0, 0.35); transform: translateY(0); transition: transform 220ms var(--ease-out), opacity 180ms var(--ease-out); }
.sheet-handle { width: 74rpx; height: 8rpx; margin: 0 auto 20rpx; border-radius: 999rpx; background: var(--line); }
.process-head { display: flex; align-items: center; justify-content: space-between; min-width: 0; gap: 20rpx; }
.process-title { flex: 0 0 auto; color: var(--text); font-size: 29rpx; font-weight: 700; }
.process-unit { overflow: hidden; color: var(--muted); font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
.process-scroll { width: 100%; margin-top: 18rpx; white-space: nowrap; }
.process-row { display: flex; gap: 12rpx; padding-right: 28rpx; }
.process-chip { display: inline-flex; flex: 0 0 auto; align-items: center; justify-content: center; min-height: 40px; padding: 0 24rpx; border: 1rpx solid var(--line); border-radius: 19rpx; color: var(--text); background: var(--surface-2); font-size: 23rpx; line-height: 1.25; text-align: center; }
</style>
