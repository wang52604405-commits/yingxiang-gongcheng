<script setup lang="ts">
withDefaults(defineProps<{ visible: boolean; message?: string; progress?: string }>(), { message: '正在处理', progress: '' })
</script>

<template>
  <view v-if="visible" class="loading-layer">
    <view class="loading-spinner" />
    <text>{{ message }}</text>
    <text v-if="progress" class="loading-copy">{{ progress }}</text>
  </view>
</template>
