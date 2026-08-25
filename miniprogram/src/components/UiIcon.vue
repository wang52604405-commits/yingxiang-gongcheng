<script setup lang="ts">
withDefaults(defineProps<{
  name: 'home' | 'camera' | 'gallery' | 'upload' | 'user' | 'search' | 'server' | 'storage' | 'shield' | 'folder' | 'check' | 'chevron'
  size?: number
}>(), { size: 20 })
</script>

<template>
  <view class="ui-icon" :class="`icon-${name}`" :style="{ width: `${size}px`, height: `${size}px` }" aria-hidden="true">
    <view class="part part-a" />
    <view class="part part-b" />
    <view class="part part-c" />
  </view>
</template>

<style scoped>
.ui-icon { position: relative; display: inline-block; flex: 0 0 auto; color: currentColor; }
.part { position: absolute; box-sizing: border-box; }
.icon-camera .part-a { inset: 19% 8% 12%; border: 1.8px solid currentColor; border-radius: 22%; }
.icon-camera .part-b { left: 34%; top: 35%; width: 32%; height: 32%; border: 1.8px solid currentColor; border-radius: 50%; }
.icon-camera .part-c { left: 23%; top: 10%; width: 28%; height: 19%; border: 1.8px solid currentColor; border-bottom: 0; border-radius: 22% 22% 0 0; }
.icon-home .part-a { left: 17%; top: 31%; width: 66%; height: 55%; border: 1.8px solid currentColor; border-top: 0; border-radius: 0 0 15% 15%; }
.icon-home .part-b { left: 20%; top: 13%; width: 60%; height: 60%; border-top: 1.8px solid currentColor; border-left: 1.8px solid currentColor; transform: rotate(45deg); border-radius: 8%; }
.icon-home .part-c { left: 44%; bottom: 14%; width: 18%; height: 30%; border: 1.8px solid currentColor; border-bottom: 0; }
.icon-gallery .part-a { inset: 20% 8% 10% 20%; border: 1.8px solid currentColor; border-radius: 12%; }
.icon-gallery .part-b { left: 8%; top: 8%; width: 70%; height: 70%; border: 1.8px solid currentColor; border-radius: 12%; background: transparent; }
.icon-gallery .part-c { left: 28%; bottom: 25%; width: 43%; height: 30%; border-left: 1.8px solid currentColor; border-top: 1.8px solid currentColor; transform: rotate(45deg) skew(-8deg, -8deg); }
.icon-upload .part-a { left: 8%; right: 8%; bottom: 8%; height: 48%; border: 1.8px solid currentColor; border-radius: 48% 48% 30% 30%; border-top-color: transparent; }
.icon-upload .part-b { left: 48%; top: 8%; width: 1.8px; height: 62%; background: currentColor; }
.icon-upload .part-c { left: 35%; top: 11%; width: 28%; height: 28%; border-left: 1.8px solid currentColor; border-top: 1.8px solid currentColor; transform: rotate(45deg); }
.icon-user .part-a { left: 35%; top: 8%; width: 30%; height: 30%; border: 1.8px solid currentColor; border-radius: 50%; }
.icon-user .part-b { left: 16%; bottom: 8%; width: 68%; height: 43%; border: 1.8px solid currentColor; border-radius: 50% 50% 18% 18%; }
.icon-user .part-c { display: none; }
.icon-search .part-a { left: 10%; top: 8%; width: 58%; height: 58%; border: 1.8px solid currentColor; border-radius: 50%; }
.icon-search .part-b { left: 64%; top: 61%; width: 34%; height: 1.8px; background: currentColor; transform: rotate(45deg); transform-origin: left center; }
.icon-search .part-c { display: none; }
.icon-server .part-a, .icon-storage .part-a { inset: 10% 8%; border: 1.8px solid currentColor; border-radius: 18%; }
.icon-server .part-b { left: 17%; right: 17%; top: 42%; height: 1.8px; background: currentColor; box-shadow: 0 28% 0 currentColor; }
.icon-server .part-c { right: 20%; top: 24%; width: 10%; height: 10%; border-radius: 50%; background: currentColor; box-shadow: 0 200% 0 currentColor; }
.icon-storage .part-a { border-radius: 50%; }
.icon-storage .part-b { left: 8%; right: 8%; top: 32%; height: 36%; border-top: 1.8px solid currentColor; border-bottom: 1.8px solid currentColor; }
.icon-storage .part-c { display: none; }
.icon-shield .part-a { left: 17%; top: 7%; width: 66%; height: 82%; border: 1.8px solid currentColor; border-radius: 42% 42% 52% 52%; }
.icon-shield .part-b, .icon-check .part-a { left: 29%; top: 46%; width: 42%; height: 22%; border-left: 1.8px solid currentColor; border-bottom: 1.8px solid currentColor; transform: rotate(-45deg); }
.icon-shield .part-c, .icon-check .part-b, .icon-check .part-c { display: none; }
.icon-folder .part-a { inset: 25% 7% 12%; border: 1.8px solid currentColor; border-radius: 12%; }
.icon-folder .part-b { left: 10%; top: 13%; width: 40%; height: 20%; border: 1.8px solid currentColor; border-bottom: 0; border-radius: 15% 15% 0 0; }
.icon-folder .part-c { display: none; }
.icon-chevron .part-a { left: 28%; top: 20%; width: 42%; height: 42%; border-right: 1.8px solid currentColor; border-bottom: 1.8px solid currentColor; transform: rotate(-45deg); }
.icon-chevron .part-b, .icon-chevron .part-c { display: none; }
</style>
