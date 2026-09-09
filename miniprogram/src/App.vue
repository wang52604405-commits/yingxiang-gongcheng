<script setup lang="ts">
import { onAppHide, onLaunch, onAppShow } from '@dcloudio/uni-app'
import { BUILD_CHANNEL } from '@/config/env'
import { createSessionLifecycle } from '@/services/session-lifecycle'
import { ensureSession, sessionState } from '@/services/auth'
import { queueRuntime } from '@/services/queue-runtime'
import { selectionStorage } from '@/stores/selection'
import { rememberLaunchInvite } from '@/services/pending-invite'

const sessionLifecycle = createSessionLifecycle({ ensure: ensureSession, session: sessionState, queue: queueRuntime, selection: selectionStorage })

onLaunch((options) => {
  rememberLaunchInvite(options, 'launch')
  console.info(BUILD_CHANNEL)
  void sessionLifecycle.activate()
})

onAppShow((options) => {
  rememberLaunchInvite(options, 'show')
  void sessionLifecycle.activate()
})

onAppHide(() => {
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
