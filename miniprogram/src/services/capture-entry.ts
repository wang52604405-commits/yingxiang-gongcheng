import { selectionStorage } from '@/stores/selection'
import type { CaptureRequirementRef, PhotoCategory, Scope, UploadMode } from '@/types/domain'

export type CaptureSource = 'camera' | 'album'

export interface CaptureLaunchOptions {
  scope?: Scope
  category?: PhotoCategory
  mode?: UploadMode
  requirement?: CaptureRequirementRef
}

/** 统一影像采集入口：页面不再分别暴露“拍照”和“上传”。 */
export async function chooseCaptureSource(): Promise<CaptureSource | null> {
  return new Promise((resolve) => {
    uni.showActionSheet({
      itemList: ['现场拍照', '从手机相册选择'],
      success: ({ tapIndex }) => resolve(tapIndex === 0 ? 'camera' : tapIndex === 1 ? 'album' : null),
      fail: () => resolve(null),
    })
  })
}

export async function launchCapture(options: CaptureLaunchOptions = {}): Promise<boolean> {
  if (!selectionStorage.hasProject()) {
    uni.showModal({
      title: '尚未同步工程',
      content: '请先在原电脑登录同一账号并完成工程账号绑定，手机拉取到真实工程后才能采集。',
      showCancel: false,
    })
    return false
  }
  const source = await chooseCaptureSource()
  if (!source) return false
  selectionStorage.setUploadPreset({
    scope: options.scope || 'engineering',
    category: options.category || 'construction',
    mode: options.mode || 'direct',
    requirement: options.requirement,
  })
  uni.navigateTo({ url: `/pages/upload/index?source=${source}&autopick=1` })
  return true
}
