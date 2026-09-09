<script setup lang="ts">
import { ref, watch } from 'vue'
const props = defineProps<{ visible: boolean; busy: boolean; error?: string; message?: string }>()
const emit = defineEmits<{ confirm: [password: string]; close: [] }>()
const password = ref('')
watch(() => props.visible, () => { password.value = '' })
</script>
<template>
  <view v-if="visible" class="password-mask"><view class="password-panel">
    <text class="password-title">输入项目删除密码</text>
    <text class="password-copy">{{ message || '删除后照片会从列表移除，电脑同步后保留回收备份。' }}</text>
    <input v-model="password" password class="password-input" maxlength="100" placeholder="项目删除密码" :disabled="busy" />
    <text v-if="error" class="password-error">{{ error }}</text>
    <view class="password-actions"><button :disabled="busy" @tap="emit('close')">取消</button><button class="delete" :disabled="busy || !password" @tap="emit('confirm', password)">{{ busy ? '正在验证…' : '验证并删除' }}</button></view>
  </view></view>
</template>
<style scoped>
.password-mask{position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.6);display:flex;align-items:center;padding:36rpx}.password-panel{width:100%;padding:30rpx;border-radius:24rpx;background:var(--surface,#122024)}.password-title{display:block;font-size:32rpx;font-weight:700}.password-copy{display:block;margin:18rpx 0;color:var(--muted);font-size:25rpx;line-height:1.6}.password-input{height:52px;padding:0 20rpx;border:1px solid var(--line);border-radius:12rpx;background:var(--surface-2);color:var(--text)}.password-error{display:block;color:#ff9a9a;margin-top:18rpx;font-size:24rpx}.password-actions{display:flex;gap:16rpx;margin-top:26rpx}.password-actions button{flex:1;min-height:44px;font-size:25rpx;background:var(--surface-2);color:var(--text)}.password-actions .delete{color:white;background:#b64141}
</style>
