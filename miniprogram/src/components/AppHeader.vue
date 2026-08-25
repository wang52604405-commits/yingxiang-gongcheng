<script setup lang="ts">
import { readNavigationLayout } from '@/utils/navigation-layout'

const props = defineProps<{
  projectName: string
  online?: boolean
}>()

defineEmits<{
  selectProject: []
}>()

const layout = readNavigationLayout()
const safeTopFallback = layout.statusBarHeight > 0 ? '' : ' + env(safe-area-inset-top)'
const spacerStyle: Record<string, string> = {
  height: safeTopFallback ? `calc(${layout.appHeaderHeight}px${safeTopFallback})` : `${layout.appHeaderHeight}px`,
}
const headerStyle: Record<string, string> = {
  height: spacerStyle.height,
  paddingTop: layout.statusBarHeight > 0 ? `${layout.statusBarHeight}px` : 'env(safe-area-inset-top)',
  '--nav-row-height': `${layout.navigationBarHeight}px`,
  '--menu-right-clearance': `${layout.menuRightClearance}px`,
}
</script>

<template>
  <view class="app-header-spacer" :style="spacerStyle">
    <view class="app-header" :style="headerStyle">
      <view class="navigation-row">
        <view class="brand-block">
          <view class="eyebrow-line">
            <text class="eyebrow">工程影像</text>
            <view v-if="props.online === false" class="offline-state">
              <text class="offline-dot" />
              <text>离线</text>
            </view>
          </view>
          <button class="project-button pressable" @tap="$emit('selectProject')">
            <text class="project-name">{{ projectName }}</text>
            <view class="chevron" aria-hidden="true" />
          </button>
        </view>
      </view>
    </view>
  </view>
</template>

<style scoped>
.app-header-spacer { width: 100%; }
.app-header {
  position: fixed;
  z-index: 20;
  top: 0;
  left: 0;
  right: 0;
  padding-left: 30rpx;
  color: #efffff;
  background: var(--top);
  box-shadow: 0 1rpx 0 rgba(255, 255, 255, 0.06);
}
.navigation-row { display: flex; align-items: center; height: var(--nav-row-height); padding-right: var(--menu-right-clearance); }
.brand-block { display: flex; flex: 1; flex-direction: column; min-width: 0; gap: 5rpx; }
.eyebrow-line { display: flex; align-items: center; min-width: 0; gap: 12rpx; }
.eyebrow { display: block; font-size: 21rpx; line-height: 1.15; opacity: 0.78; }
.project-button { display: flex; align-items: center; justify-content: flex-start; width: 100%; min-height: 36rpx; padding: 0; color: inherit; text-align: left; background: transparent; }
.project-name { overflow: hidden; font-size: 27rpx; font-weight: 600; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.chevron { flex: 0 0 auto; width: 13rpx; height: 13rpx; margin: -6rpx 0 0 13rpx; border-right: 2rpx solid currentColor; border-bottom: 2rpx solid currentColor; transform: rotate(45deg); }
.offline-state { display: flex; align-items: center; gap: 7rpx; color: #ffd28b; font-size: 19rpx; white-space: nowrap; }
.offline-dot { width: 11rpx; height: 11rpx; border-radius: 50%; background: #f1b34b; box-shadow: 0 0 0 5rpx rgba(241, 179, 75, 0.13); }
</style>
