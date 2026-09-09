<script setup lang="ts">
import { watch } from 'vue'
import { createStablePhotoImage } from '@/services/stable-photo-image'
const props = defineProps<{ src: string; identity: string; lazyLoad?: boolean }>()
const image = createStablePhotoImage()
watch(() => [props.src, props.identity], () => image.setSource(props.src, props.identity), { immediate: true })
</script>

<template>
  <view class="stable-photo">
    <template v-for="(slot, index) in image.state.slots" :key="slot.id">
      <image v-if="slot.url" class="stable-photo-layer" :src="slot.url" mode="aspectFill"
        :lazy-load="lazyLoad" :style="{ opacity: image.state.displayed === index ? 1 : 0 }"
        @load="image.loaded(index, slot.id)" @error="image.failed(index, slot.id)" />
    </template>
  </view>
</template>

<style scoped>
.stable-photo { position: relative; width: 100%; height: 100%; overflow: hidden; }
.stable-photo-layer { position: absolute; inset: 0; width: 100%; height: 100%; }
</style>
