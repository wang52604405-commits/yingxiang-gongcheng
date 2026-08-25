<script setup lang="ts">
withDefaults(defineProps<{ title: string; subtitle?: string; back?: boolean }>(), { subtitle: '', back: true })

function goBack() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/home/index' })
}
</script>

<template>
  <view class="page-header">
    <button v-if="back" class="back-button pressable" aria-label="返回" @tap="goBack"><view class="back-chevron" aria-hidden="true" /></button>
    <view class="header-copy">
      <text class="header-title">{{ title }}</text>
      <text v-if="subtitle" class="header-subtitle">{{ subtitle }}</text>
    </view>
    <view class="header-slot"><slot /></view>
  </view>
</template>

<style scoped>
.page-header {
  position: fixed;
  z-index: 25;
  top: 0;
  left: 0;
  right: 0;
  display: grid;
  grid-template-columns: 74rpx 1fr 74rpx;
  align-items: end;
  min-height: calc(150rpx + env(safe-area-inset-top));
  padding: calc(22rpx + env(safe-area-inset-top)) 20rpx 24rpx;
  border-bottom: 1rpx solid rgba(255, 255, 255, 0.07);
  background: var(--top);
}
.back-button { display: grid; place-items: center; width: 68rpx; height: 68rpx; border-radius: 22rpx; color: #fff; background: rgba(255, 255, 255, 0.08); line-height: 1; }
.back-chevron { width: 17rpx; height: 17rpx; margin-left: 7rpx; border-right: 3rpx solid currentColor; border-bottom: 3rpx solid currentColor; transform: rotate(135deg); }
.header-copy { min-width: 0; text-align: center; }
.header-title { display: block; overflow: hidden; color: #fff; font-size: 31rpx; font-weight: 600; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.header-subtitle { display: block; overflow: hidden; margin-top: 4rpx; color: rgba(255, 255, 255, 0.68); font-size: 21rpx; text-overflow: ellipsis; white-space: nowrap; }
.header-slot { display: flex; justify-content: flex-end; }
</style>
