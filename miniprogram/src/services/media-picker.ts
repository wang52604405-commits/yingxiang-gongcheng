async function ensurePrivacyAuthorized(): Promise<void> {
  const wxApi = (globalThis as { wx?: any }).wx
  if (!wxApi?.requirePrivacyAuthorize) return
  await new Promise<void>((resolve, reject) => {
    wxApi.requirePrivacyAuthorize({ success: () => resolve(), fail: reject })
  })
}

function pickerErrorText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  if (error && typeof error === 'object' && 'errMsg' in error) {
    const message = String((error as { errMsg?: unknown }).errMsg || '').trim()
    if (message) return message
  }
  return String(error || '').trim() || '照片选择接口调用失败'
}

function isPickerCancelled(error: unknown): boolean {
  return /cancel/i.test(pickerErrorText(error))
}

function normalizePhotoPaths(result: any): string[] {
  const paths = Array.isArray(result?.tempFilePaths)
    ? result.tempFilePaths
    : (Array.isArray(result?.tempFiles) ? result.tempFiles : [])
      .map((file: { tempFilePath?: string; path?: string }) => file?.tempFilePath || file?.path)
  return paths.filter((path: unknown): path is string => typeof path === 'string' && Boolean(path))
}

// wx.chooseImage / wx.chooseMedia 的稳定多选上限均按 9 张处理。
// 旧实现根据基础库版本把 chooseImage.count 提高到 20，部分真机会在打开
// 系统相册前直接失败；因此这里不再按 SDK 放大 count。
export function getAlbumSelectionLimit(): number {
  return 9
}

function chooseWithMedia(source: 'camera' | 'album'): Promise<any> {
  const wxApi = (globalThis as { wx?: any }).wx
  if (!wxApi?.chooseMedia) return Promise.reject(new Error('wx.chooseMedia unavailable'))
  return new Promise<any>((resolve, reject) => {
    wxApi.chooseMedia({
      count: source === 'camera' ? 1 : getAlbumSelectionLimit(),
      mediaType: ['image'],
      sourceType: [source],
      sizeType: ['original'],
      success: resolve,
      fail: reject,
    })
  })
}

function chooseWithImage(source: 'camera' | 'album'): Promise<any> {
  return new Promise<any>((resolve, reject) => {
    const options = {
      count: source === 'camera' ? 1 : getAlbumSelectionLimit(),
      sourceType: [source],
      // 原图由服务器保存并生成预览，手机端不再调用不稳定的微信压缩接口。
      sizeType: ['original'],
      success: resolve,
      fail: reject,
    }
    const wxApi = (globalThis as { wx?: any }).wx
    if (wxApi?.chooseImage) wxApi.chooseImage(options)
    else (uni as any).chooseImage(options)
  })
}

export async function choosePhotoPaths(source: 'camera' | 'album'): Promise<string[]> {
  await ensurePrivacyAuthorized()
  const wxApi = (globalThis as { wx?: any }).wx

  // 基础库 2.21.0 起 chooseImage 已停止维护。真机优先走 chooseMedia；
  // 若设备/基础库实现异常，再自动降级到 chooseImage，保证旧机仍可选图。
  if (wxApi?.chooseMedia) {
    try {
      return normalizePhotoPaths(await chooseWithMedia(source))
    } catch (error) {
      if (isPickerCancelled(error)) throw error
      // 非用户取消才降级，避免用户点“取消”后又弹第二个系统选择器。
    }
  }

  try {
    return normalizePhotoPaths(await chooseWithImage(source))
  } catch (error) {
    if (isPickerCancelled(error)) throw error
    const label = source === 'album' ? '相册' : '相机'
    throw new Error(`${label}打开失败：${pickerErrorText(error)}`)
  }
}
