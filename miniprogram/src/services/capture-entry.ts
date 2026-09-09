import { selectionStorage } from '@/stores/selection'
import type { CaptureRequirementRef, PhotoCategory, Scope, UploadMode } from '@/types/domain'
import { capturePermissionMessage } from './project-membership'

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
  const project = selectionStorage.getProject()
  const denied = capturePermissionMessage(project)
  if (denied && !project?.id) {
    uni.showModal({ title: denied.title, content: denied.content, showCancel: false, success: () => {
      if (!project?.id) uni.navigateTo({ url: '/pages/project/select' })
    } })
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
  uni.navigateTo({ url: source === 'camera' ? '/pages/photo/watermark?camera=1' : '/pages/upload/index?source=album&autopick=1' })
  return true
}
