<script setup lang="ts">
import { readNavigationLayout } from '@/utils/navigation-layout'

const props = defineProps<{
  projectName: string
  online?: boolean
  pendingReviews?: number
}>()

defineEmits<{
  selectProject: []
  openApplications: []
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
        <button class="brand-block pressable" @tap="$emit('selectProject')">
          <view class="project-line">
            <text class="project-name">{{ projectName }}</text>
            <view v-if="props.online === false" class="offline-state">
              <text class="offline-dot" />
              <text>离线</text>
            </view>
            <view class="chevron" aria-hidden="true" />
          </view>
        </button>
        <button
          v-if="Number(props.pendingReviews || 0) > 0"
          class="review-alert pressable"
          aria-label="有待审核的项目加入申请"
          @tap="$emit('openApplications')"
        >
          <text class="review-alert-label">申请</text>
          <text class="review-alert-badge">{{ Number(props.pendingReviews || 0) > 99 ? '99+' : props.pendingReviews }}</text>
        </button>
      </view>
    </view>
  </view>
</template>

<style scoped>
.app-header-spacer { width: 100%; margin-bottom: var(--space-lg); }
.app-header {
  position: fixed;
  z-index: 20;
  top: 0;
  left: 0;
  right: 0;
  padding-left: 30rpx;
  color: var(--header-text, #efffff);
  background: var(--top);
  box-shadow: 0 1rpx 0 rgba(255, 255, 255, 0.06);
}
.navigation-row { display: flex; align-items: center; gap: 14rpx; height: var(--nav-row-height); padding-right: var(--menu-right-clearance); }
.brand-block { display: flex; flex: 1; align-items: stretch; justify-content: center; align-self: stretch; min-width: 0; margin: 0; padding: 0; color: inherit; text-align: left; background: transparent; }
.project-line { display: flex; align-items: center; justify-content: flex-start; width: 100%; min-height: 36rpx; }
.project-name { display: block; flex: 1; min-width: 0; overflow: hidden; font-size: 29rpx; font-weight: 600; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.chevron { flex: 0 0 auto; width: 13rpx; height: 13rpx; margin: -6rpx 0 0 13rpx; border-right: 2rpx solid currentColor; border-bottom: 2rpx solid currentColor; transform: rotate(45deg); }
.offline-state { display: flex; flex: 0 0 auto; align-items: center; gap: 7rpx; margin-left: 14rpx; color: var(--warning); font-size: 21rpx; white-space: nowrap; }
.offline-dot { width: 11rpx; height: 11rpx; border-radius: 50%; background: #f1b34b; box-shadow: 0 0 0 5rpx rgba(241, 179, 75, 0.13); }
.review-alert { position: relative; display: flex; flex: 0 0 auto; align-items: center; justify-content: center; min-width: 82rpx; height: 58rpx; margin: 0; padding: 0 14rpx; border: 1rpx solid rgba(255, 255, 255, .18); border-radius: 18rpx; color: var(--header-text, #efffff); background: rgba(255, 255, 255, .08); }
.review-alert-label { font-size: 22rpx; font-weight: 600; line-height: 1; }
.review-alert-badge { position: absolute; top: -9rpx; right: -9rpx; display: flex; align-items: center; justify-content: center; min-width: 30rpx; height: 30rpx; padding: 0 7rpx; border: 3rpx solid var(--top); border-radius: 18rpx; color: #fff; background: #d6453d; font-size: 18rpx; font-weight: 700; line-height: 1; }
</style>
