<script setup lang="ts">
defineProps<{ selected: number; badge?: number }>()
import UiIcon from './UiIcon.vue'
const tabs = [
  ['/pages/home/index', 'home', '工作台'],
  ['/pages/library/index', 'gallery', '影像库'],
  ['/pages/upload/index', 'camera', '上传'],
  ['/pages/queue/index', 'upload', '待上传'],
  ['/pages/profile/index', 'user', '我的'],
] as const
const switchTo = (url: string) => uni.switchTab({ url })
</script>

<template>
  <view class="h5-tabbar">
    <button v-for="(tab, index) in tabs" :key="tab[0]" class="h5-tab pressable" :class="{ active: selected === index, primary: index === 2 }" @tap="switchTo(tab[0])">
      <view class="h5-icon"><UiIcon :name="tab[1]" :size="21" /><text v-if="index === 3 && badge" class="h5-badge">{{ Math.min(99, badge) }}</text></view>
      <text>{{ tab[2] }}</text>
    </button>
  </view>
</template>

<style scoped>
.h5-tabbar { position: fixed; z-index: 60; left: 0; right: 0; bottom: 0; display: grid; grid-template-columns: repeat(5, 1fr); height: calc(138rpx + env(safe-area-inset-bottom)); padding: 10rpx 10rpx calc(12rpx + env(safe-area-inset-bottom)); border-top: 1rpx solid var(--line); background: var(--surface); }
.h5-tab { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5rpx; overflow: visible; padding: 0; color: var(--muted); background: transparent; font-size: 21rpx; }
.h5-tab.active { color: var(--primary-strong); }
.h5-icon { position: relative; display: grid; place-items: center; width: 42rpx; height: 42rpx; line-height: 1; }
.h5-tab.primary .h5-icon { display: grid; place-items: center; width: 82rpx; height: 82rpx; margin-top: -34rpx; border: 7rpx solid var(--surface); border-radius: 27rpx; color: #041a1a; background: var(--primary-strong); }
.h5-badge { position: absolute; top: -8rpx; right: -14rpx; min-width: 28rpx; padding: 3rpx 7rpx; border-radius: 999rpx; color: #241700; background: var(--warning); font-size: 17rpx; }
</style>
