<script setup lang="ts">
import { readNavigationLayout } from '@/utils/navigation-layout'

withDefaults(defineProps<{ title: string; subtitle?: string; back?: boolean }>(), { subtitle: '', back: true })

const layout = readNavigationLayout()
const safeTopFallback = layout.statusBarHeight > 0 ? '' : ' + env(safe-area-inset-top)'
const spacerStyle: Record<string, string> = {
  height: safeTopFallback ? `calc(${layout.pageHeaderHeight}px${safeTopFallback})` : `${layout.pageHeaderHeight}px`,
}
const headerStyle: Record<string, string> = {
  height: spacerStyle.height,
  paddingTop: layout.statusBarHeight > 0 ? `${layout.statusBarHeight}px` : 'env(safe-area-inset-top)',
  paddingRight: `${layout.menuRightClearance}px`,
  '--nav-row-height': `${layout.navigationBarHeight}px`,
}

function goBack() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/home/index' })
}
</script>

<template>
  <view class="page-header-spacer" :style="spacerStyle">
    <view class="page-header" :style="headerStyle">
      <view class="back-slot">
        <button v-if="back" class="back-button pressable" aria-label="返回" @tap="goBack"><view class="back-chevron" aria-hidden="true" /></button>
      </view>
      <view class="header-copy">
        <text class="header-title">{{ title }}</text>
        <text v-if="subtitle" class="header-subtitle">{{ subtitle }}</text>
      </view>
      <view class="header-slot"><slot /></view>
    </view>
  </view>
</template>

<style scoped>
.page-header-spacer { width: 100%; margin-bottom: var(--space-lg); }
.page-header {
  position: fixed;
  z-index: 25;
  top: 0;
  left: 0;
  right: 0;
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) 0;
  align-items: center;
  padding-left: 20rpx;
  border-bottom: 1rpx solid var(--line);
  background: var(--top);
}
.back-slot { display: flex; align-items: center; height: var(--nav-row-height); }
.back-button { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 22rpx; color: var(--header-text, #fff); background: rgba(255, 255, 255, 0.08); line-height: 1; }
.back-chevron { width: 17rpx; height: 17rpx; margin-left: 7rpx; border-right: 3rpx solid currentColor; border-bottom: 3rpx solid currentColor; transform: rotate(135deg); }
.header-copy { min-width: 0; text-align: center; }
.header-title { display: block; overflow: hidden; color: var(--header-text, #fff); font-size: 30rpx; font-weight: 600; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.header-subtitle { display: block; overflow: hidden; margin-top: 2rpx; color: var(--header-muted, rgba(255, 255, 255, 0.7)); font-size: 22rpx; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.header-slot { display: flex; justify-content: flex-end; min-width: 0; }
</style>
