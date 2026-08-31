async function ensurePrivacyAuthorized(): Promise<void> {
  const wxApi = (globalThis as { wx?: any }).wx
  if (!wxApi?.requirePrivacyAuthorize) return
  await new Promise<void>((resolve, reject) => {
    wxApi.requirePrivacyAuthorize({ success: () => resolve(), fail: reject })
  })
}

function compareVersion(left: string, right: string): number {
  const a = left.split('.').map(Number)
  const b = right.split('.').map(Number)
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    const difference = (a[index] || 0) - (b[index] || 0)
    if (difference) return difference
  }
  return 0
}

export function getAlbumSelectionLimit(): number {
  const wxApi = (globalThis as { wx?: any }).wx
  const sdkVersion = String(wxApi?.getSystemInfoSync?.().SDKVersion || '')
  return sdkVersion && compareVersion(sdkVersion, '2.25.0') < 0 ? 9 : 20
}

export async function choosePhotoPaths(source: 'camera' | 'album'): Promise<string[]> {
  await ensurePrivacyAuthorized()
  const result = await new Promise<any>((resolve, reject) => {
    const options = {
      count: source === 'camera' ? 1 : getAlbumSelectionLimit(),
      sourceType: [source],
      // 原图由服务器保存并生成预览，手机端不再调用不稳定的微信压缩接口。
      // 选择器仅取原图，避免系统“原图”勾选状态导致实际文件规格不一致。
      sizeType: ['original'],
      success: resolve,
      fail: reject,
    }
    const wxApi = (globalThis as { wx?: any }).wx
    if (wxApi?.chooseImage) wxApi.chooseImage(options)
    else (uni as any).chooseImage(options)
  })
  const paths = Array.isArray(result.tempFilePaths)
    ? result.tempFilePaths
    : (result.tempFiles || []).map((file: { tempFilePath?: string; path?: string }) => file.tempFilePath || file.path)
  return paths.filter(Boolean)
}
