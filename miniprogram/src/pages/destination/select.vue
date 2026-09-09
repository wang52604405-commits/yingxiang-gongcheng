<script setup lang="ts">
import { themeStyle } from '@/services/theme'
import { matchesDivisionKeywords, resolveWatermarkDivision, saveWatermarkDivision } from '@/services/watermark-division'
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import PageHeader from '@/components/PageHeader.vue'
import UiIcon from '@/components/UiIcon.vue'
import { loadDestinationTree } from '@/services/destination-tree'
import { selectionStorage, type DestinationSelection } from '@/stores/selection'
import { destinationKey, destinationLabel, flattenDestinations, getDestinationHistory, reconcileDestination, rememberDestination, setPhotoEditDestination, toggleFavoriteDestination, type SelectableDestination } from '@/services/destination-history'
import type { ProjectNode, Scope } from '@/types/domain'

const scope = ref<Scope>('engineering')
const keyword = ref('')
const loading = ref(true)
const loadError = ref('')
const roots = ref<ProjectNode[]>([])
const trail = ref<ProjectNode[]>([])
const selectedNode = ref<SelectableDestination | null>(null)
const returnTarget = ref('capture')
const targetProjectId = ref('')
const targetProjectName = ref('')
const owner = ref('')
const history = ref<ReturnType<typeof getDestinationHistory>>({ recent: [], favorites: [] })
const allNodes = computed(() => flattenDestinations(roots.value))
const leafNodes = computed(() => allNodes.value.filter((node) => scope.value === 'engineering'
  ? node.type === 'unit' : node.type === 'other' && !node.children?.length))
const searchResults = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return leafNodes.value.filter((node) => matchesDivisionKeywords(node, query))
})
const browseNodes = computed(() => (trail.value.length ? trail.value[trail.value.length - 1].children || [] : roots.value)
  .filter((node) => node.active !== false && (node.type === 'unit' || node.type === 'other' || flattenDestinations([node]).some((item) => item.type === 'unit'))))
const recent = computed(() => validHistory(history.value.recent))
const favorites = computed(() => validHistory(history.value.favorites))
const hasProcessSheet = computed(() => scope.value === 'engineering' && selectedNode.value?.processes?.length && !['library', 'watermark'].includes(returnTarget.value))
function validHistory(items: DestinationSelection[]) {
  return items.filter((item) => item.scope === scope.value).map((item) => returnTarget.value === 'watermark' ? resolveWatermarkDivision(item, allNodes.value) : reconcileDestination(item, allNodes.value)).filter((item): item is DestinationSelection => Boolean(item))
}
function refreshHistory() { history.value = getDestinationHistory(owner.value, targetProjectId.value) }
function isFavorite(value: DestinationSelection) { return favorites.value.some((item) => destinationKey(item) === destinationKey(value)) }
function toggleFavorite(value: DestinationSelection) {
  toggleFavoriteDestination(owner.value, targetProjectId.value, value)
  refreshHistory()
}
async function loadTree() {
  loading.value = true
  loadError.value = ''
  try {
    const activeProject = selectionStorage.getProject()
    const projectId = returnTarget.value === 'confirm' ? targetProjectId.value : String(activeProject.id || '')
    if (!projectId) throw new Error('请先选择或加入工程')
    const response = await loadDestinationTree(projectId, scope.value, returnTarget.value === 'watermark')
    targetProjectId.value = projectId
    targetProjectName.value = String(response.project?.name || activeProject.name || '')
    roots.value = response.nodes || []
    const activeRoots = roots.value.filter((node) => node.active !== false)
    trail.value = activeRoots.length === 1 && activeRoots[0].type === 'contract' ? [activeRoots[0]] : []
    refreshHistory()
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '请稍后重试'
  } finally { loading.value = false }
}
function browse(node: ProjectNode) {
  selectedNode.value = null
  if (node.type === 'unit' || (scope.value === 'other' && !node.children?.length)) {
    const part = [...trail.value].reverse().find((item) => item.type === 'part')
    const unitProject = [...trail.value].reverse().find((item) => item.type === 'unit_project')
    const selected = leafNodes.value.find((item) => item.code === node.code && item.pathLabel === trail.value.map((parent) => parent.name).join(' / ') && (!part || item.assignment.part_code === part.code) && (!unitProject || item.assignment.unit_project_code === unitProject.code))
    if (selected) chooseNode(selected)
  } else trail.value = [...trail.value, node]
}
function chooseNode(node: SelectableDestination) {
  selectedNode.value = node
  if (['library', 'watermark'].includes(returnTarget.value) || scope.value === 'other' || !node.processes?.length) saveSelection()
}
function finish(value: DestinationSelection) {
  if (owner.value !== selectionStorage.getOwner()) return
  if (returnTarget.value !== 'confirm' && String(selectionStorage.getProject().id || '') !== targetProjectId.value) return
  if (returnTarget.value === 'watermark') saveWatermarkDivision(owner.value, targetProjectId.value, value)
  else if (returnTarget.value === 'library') selectionStorage.setLibraryFilter(value)
  else if (returnTarget.value === 'confirm') {
    if (!targetProjectId.value) return
    selectionStorage.setConfirmDestination({ ...value, project_id: targetProjectId.value, project_name: targetProjectName.value })
  } else if (returnTarget.value === 'photo-edit') setPhotoEditDestination(owner.value, targetProjectId.value, value)
  else selectionStorage.setDestination(value)
  if (returnTarget.value !== 'library') rememberDestination(owner.value, targetProjectId.value, value)
  uni.navigateBack()
}
function reuse(value: DestinationSelection) {
  const valid = returnTarget.value === 'watermark' ? resolveWatermarkDivision(value, allNodes.value) : reconcileDestination(value, allNodes.value)
  if (!valid) return
  // The library filters a whole unit, never a single process.
  if (returnTarget.value === 'library') delete valid.assignment.process_name
  finish(valid)
}
function saveSelection(processName = '') {
  const node = selectedNode.value
  if (!node) return
  finish({ scope: scope.value, assignment: scope.value === 'engineering' ? { ...node.assignment, process_name: processName } : { ...node.assignment }, project_id: targetProjectId.value, project_name: targetProjectName.value })
}
onLoad((query) => {
  scope.value = query?.scope === 'other' ? 'other' : 'engineering'
  returnTarget.value = String(query?.return || 'capture')
  targetProjectId.value = returnTarget.value === 'confirm' ? String(query?.project_id || '') : ''
  keyword.value = String(query?.keyword || '')
  owner.value = selectionStorage.getOwner()
  void loadTree()
})
</script>

<template>
  <page-meta :page-style="themeStyle" />
  <view class="page-shell no-tabs destination-page" :class="{ 'has-process-sheet': hasProcessSheet }">
    <PageHeader :title="returnTarget === 'library' && scope === 'engineering' ? '选择单元' : scope === 'engineering' ? '选择工程部位' : '选择其它影像目录'" />
    <view class="search-box"><UiIcon class="search-icon" name="search" :size="19" /><input v-model="keyword" placeholder="搜索名称、编码或多个关键词" placeholder-class="input-placeholder" /><button v-if="keyword" class="clear-search pressable" @tap="keyword = ''">清除</button></view>
    <view v-if="loading" class="empty-state"><view class="loading-spinner" /><text class="empty-copy">加载中…</text></view>
    <view v-else-if="loadError" class="empty-state"><text class="empty-title">工程层级读取失败</text><text class="empty-copy">{{ loadError }}</text><button class="retry-button pressable" @tap="loadTree">重新加载</button></view>
    <template v-else>
      <template v-if="!keyword.trim()">
        <view v-if="recent.length" class="shortcut-section">
          <view class="section-head"><text class="section-title">最近使用</text><button class="reuse-button pressable" @tap="reuse(recent[0])">沿用上次</button></view>
          <view class="card shortcut-list"><view v-for="item in recent.slice(0, 4)" :key="destinationKey(item)" class="shortcut-row">
            <button class="shortcut-main pressable" @tap="reuse(item)"><text>{{ destinationLabel(item) }}</text></button>
            <button class="favorite-button pressable" :class="{ saved: isFavorite(item) }" @tap="toggleFavorite(item)">{{ isFavorite(item) ? '已收藏' : '收藏' }}</button>
          </view></view>
        </view>
        <view v-if="favorites.length" class="shortcut-section"><text class="section-title">收藏部位</text>
          <view class="card shortcut-list"><view v-for="item in favorites" :key="destinationKey(item)" class="shortcut-row">
            <button class="shortcut-main pressable" @tap="reuse(item)"><text>{{ destinationLabel(item) }}</text></button>
            <button class="favorite-button saved pressable" @tap="toggleFavorite(item)">取消收藏</button>
          </view></view>
        </view>
        <view class="section-head"><text class="section-title">按层级选择</text><button v-if="trail.length" class="reuse-button pressable" @tap="trail = trail.slice(0, -1); selectedNode = null">返回上级</button></view>
        <view class="breadcrumbs"><button class="crumb pressable" @tap="trail = []; selectedNode = null">全部</button><template v-for="(item, index) in trail" :key="item.code"><text> / </text><button class="crumb pressable" @tap="trail = trail.slice(0, index + 1); selectedNode = null">{{ item.name }}</button></template></view>
        <view v-if="browseNodes.length" class="node-list card"><button v-for="node in browseNodes" :key="node.code" class="node-card pressable" :class="{ active: selectedNode?.code === node.code }" @tap="browse(node)">
          <view class="node-copy"><text class="node-name">{{ node.name }}</text><text class="node-code">{{ node.code }}</text></view><text class="node-arrow">{{ selectedNode?.code === node.code ? '✓' : '›' }}</text>
        </button></view>
        <view v-else class="empty-state"><text class="empty-title">此层级暂无可选部位</text></view>
      </template>
      <template v-else>
        <text class="result-count">找到 {{ searchResults.length }} 个部位</text>
        <view v-if="searchResults.length" class="node-list card"><button v-for="node in searchResults" :key="node.pathLabel + node.code" class="node-card pressable" :class="{ active: selectedNode?.code === node.code }" @tap="chooseNode(node)">
          <view class="node-copy"><text class="node-name">{{ node.name }}</text><text class="node-path">{{ node.pathLabel || '工程根目录' }}</text><text class="node-code">{{ node.code }}</text></view><text class="node-arrow">{{ selectedNode?.code === node.code ? '✓' : '›' }}</text>
        </button></view>
        <view v-else class="empty-state"><text class="empty-title">未找到相关部位</text><text class="empty-copy">试试单元名称、分部名称或编码</text></view>
      </template>
    </template>
    <view v-if="hasProcessSheet && selectedNode" class="process-sheet">
      <view class="process-head"><text class="process-title">选择工序</text><button class="reuse-button pressable" @tap="selectedNode = null">收起</button></view>
      <text class="process-path">{{ selectedNode.pathLabel }} / {{ selectedNode.name }}</text>
      <scroll-view scroll-y class="process-scroll"><view class="process-row"><button v-for="process in selectedNode.processes || []" :key="process" class="process-chip pressable" @tap="saveSelection(process)">{{ process }}</button></view></scroll-view>
    </view>
  </view>
</template>

<style scoped>
.destination-page { padding-bottom: calc(40rpx + var(--safe-bottom)); }
.destination-page.has-process-sheet { padding-bottom: calc(520rpx + var(--safe-bottom)); }
.search-box { display: grid; grid-template-columns: 48rpx 1fr auto; align-items: center; gap: 8rpx; height: 86rpx; margin-bottom: 22rpx; padding: 0 22rpx; border: 1rpx solid var(--line); border-radius: 22rpx; background: var(--surface); }
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
.process-scroll { width: 100%; height: 280rpx; margin-top: 18rpx; }
.process-row { display: flex; flex-wrap: wrap; gap: 12rpx; padding-bottom: 4rpx; }
.process-chip { display: inline-flex; flex: 0 0 auto; align-items: center; justify-content: center; min-height: 44px; padding: 0 24rpx; border: 1rpx solid var(--line); border-radius: 19rpx; color: var(--text); background: var(--surface-2); font-size: 23rpx; line-height: 1.25; text-align: center; }
.shortcut-section { margin-bottom: 26rpx; }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 14rpx; margin-bottom: 10rpx; }
.section-title { display: block; color: var(--text); font-size: 26rpx; font-weight: 650; }
.shortcut-list { margin-top: 10rpx; overflow: hidden; }
.shortcut-row { display: flex; align-items: center; border-bottom: 1rpx solid var(--line); }
.shortcut-row:last-child { border: 0; }
.shortcut-main { flex: 1; min-width: 0; padding: 20rpx; min-height: 44px; color: var(--text); background: transparent; font-size: 23rpx; line-height: 1.6; text-align: left; }
.favorite-button, .reuse-button, .clear-search, .crumb { display: inline-flex; align-items: center; min-height: 44px; padding: 0 14rpx; color: var(--primary-strong); background: transparent; font-size: 22rpx; line-height: 1.5; }
.favorite-button { flex-shrink: 0; color: var(--muted); }
.favorite-button.saved { color: var(--primary-strong); }
.breadcrumbs { display: flex; flex-wrap: wrap; align-items: center; color: var(--muted); font-size: 22rpx; margin-bottom: 10rpx; }
.crumb { padding: 0 8rpx; }
.result-count { display: block; margin-bottom: 16rpx; color: var(--muted); font-size: 22rpx; }
.process-path { display: block; margin-top: 8rpx; font-size: 22rpx; line-height: 1.5; color: var(--muted); }
.retry-button { margin-top: 22rpx; padding: 12rpx 30rpx; min-height: 44px; background: var(--primary-soft); color: var(--primary-strong); font-size: 26rpx; }
</style>
