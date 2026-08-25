<script setup lang="ts">
import { onHide, onLaunch, onShow } from '@dcloudio/uni-app'
import { BUILD_CHANNEL } from '@/config/env'
import { createSessionLifecycle } from '@/services/session-lifecycle'
import { ensureSession, sessionState } from '@/services/auth'
import { queueRuntime } from '@/services/queue-runtime'
import { selectionStorage } from '@/stores/selection'

const sessionLifecycle = createSessionLifecycle({ ensure: ensureSession, session: sessionState, queue: queueRuntime, selection: selectionStorage })

onLaunch(() => {
  console.info(BUILD_CHANNEL)
  void sessionLifecycle.activate()
})

onShow(() => {
  void sessionLifecycle.activate()
})

onHide(() => {
  sessionLifecycle.hide()
})
</script>

<style>
page {
  min-height: 100%;
  background: #0c181b;
  color: #f5fbfa;
}

/* #ifdef H5 */
uni-tabbar {
  display: none !important;
}
/* #endif */
</style>
