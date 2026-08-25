<script setup lang="ts">
defineProps<{ selected: number; badge?: number }>()
import UiIcon from './UiIcon.vue'
import { launchCapture } from '@/services/capture-entry'
const tabs = [
  { url: '/pages/home/index', icon: 'home', label: '工作台', visualIndex: 0 },
  { url: '/pages/library/index', icon: 'gallery', label: '影像库', visualIndex: 1 },
  { url: '', icon: 'camera', label: '采集', visualIndex: 2, action: true },
  { url: '/pages/queue/index', icon: 'upload', label: '待上传', visualIndex: 3 },
  { url: '/pages/profile/index', icon: 'user', label: '我的', visualIndex: 4 },
] as const
function activate(tab: typeof tabs[number]) {
  if ('action' in tab && tab.action) { void launchCapture({ scope: 'engineering', category: 'construction', mode: 'direct' }); return }
  if (tab.url) uni.switchTab({ url: tab.url })
}
</script>
<template>
  <view class="h5-tabbar">
    <button v-for="tab in tabs" :key="tab.label" class="h5-tab pressable" :class="{ active: selected === tab.visualIndex, primary: tab.visualIndex === 2 }" @tap="activate(tab)">
      <view class="h5-icon"><UiIcon :name="tab.icon" :size="21" /><text v-if="tab.visualIndex === 3 && badge" class="h5-badge">{{ Math.min(99, badge) }}</text></view><text>{{ tab.label }}</text>
    </button>
  </view>
</template>
<style scoped>
.h5-tabbar { position: fixed; z-index: 60; left: 0; right: 0; bottom: 0; display: grid; grid-template-columns: repeat(5, 1fr); height: calc(138rpx + env(safe-area-inset-bottom)); padding: 10rpx 10rpx calc(12rpx + env(safe-area-inset-bottom)); border-top: 1rpx solid var(--line); background: var(--surface); }
.h5-tab { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5rpx; width: 100%; min-width: 0; height: 100%; overflow: visible; padding: 0; color: var(--muted); background: transparent; font-size: 22rpx; font-weight: 500; line-height: 1.2; text-align: center; }
.h5-tab.active { color: var(--primary-strong); }
.h5-icon { position: relative; display: grid; place-items: center; width: 42rpx; height: 42rpx; line-height: 1; }
.h5-tab.primary { height: calc(100% + 34rpx); margin-top: -34rpx; color: var(--primary-strong); }
.h5-tab.primary .h5-icon { position: absolute; top: 0; left: 50%; display: grid; place-items: center; width: 82rpx; height: 82rpx; border: 7rpx solid var(--surface); border-radius: 27rpx; color: #041a1a; background: var(--primary-strong); transform: translateX(-50%); }
.h5-tab.primary > text { position: absolute; top: 102rpx; left: 0; right: 0; text-align: center; }
.h5-badge { position: absolute; top: -8rpx; right: -14rpx; display: grid; place-items: center; min-width: 28rpx; min-height: 28rpx; padding: 3rpx 7rpx; border-radius: 999rpx; color: #241700; background: var(--warning); font-size: 17rpx; font-weight: 700; line-height: 1; }
</style>
