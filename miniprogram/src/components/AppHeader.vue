<script setup lang="ts">
defineProps<{
  projectName: string
  online?: boolean
}>()

defineEmits<{
  selectProject: []
}>()
</script>

<template>
  <view class="app-header">
    <view class="brand-block">
      <text class="eyebrow">工程影像</text>
      <button class="project-button pressable" @tap="$emit('selectProject')">
        <text class="project-name">{{ projectName }}</text>
        <view class="chevron" aria-hidden="true" />
      </button>
    </view>
    <view class="online-state" :class="{ offline: online === false }">
      <text class="online-dot" />
      <text>{{ online === false ? '当前离线' : '网络已连接' }}</text>
    </view>
  </view>
</template>

<style scoped>
.app-header {
  position: fixed;
  z-index: 20;
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  min-height: calc(162rpx + env(safe-area-inset-top));
  padding: calc(30rpx + env(safe-area-inset-top)) 30rpx 28rpx;
  color: #efffff;
  background: var(--top);
  box-shadow: 0 1rpx 0 rgba(255, 255, 255, 0.06);
}
.brand-block { min-width: 0; }
.eyebrow { display: block; margin-bottom: 8rpx; font-size: 22rpx; line-height: 1.2; opacity: 0.78; }
.project-button { display: flex; align-items: center; justify-content: flex-start; min-height: 44rpx; max-width: 500rpx; padding: 0; color: inherit; text-align: left; background: transparent; }
.project-name { overflow: hidden; font-size: 27rpx; font-weight: 600; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.chevron { flex: 0 0 auto; width: 13rpx; height: 13rpx; margin: -6rpx 0 0 13rpx; border-right: 2rpx solid currentColor; border-bottom: 2rpx solid currentColor; transform: rotate(45deg); }
.online-state { display: flex; align-items: center; gap: 8rpx; margin-bottom: 4rpx; font-size: 21rpx; white-space: nowrap; }
.online-dot { width: 14rpx; height: 14rpx; border-radius: 50%; background: #4ee0b0; box-shadow: 0 0 0 6rpx rgba(78, 224, 176, 0.13); }
.online-state.offline { color: #ffd28b; }
.online-state.offline .online-dot { background: #f1b34b; box-shadow: 0 0 0 6rpx rgba(241, 179, 75, 0.13); }
</style>
