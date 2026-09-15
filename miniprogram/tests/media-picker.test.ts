import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  delete (globalThis as { wx?: unknown }).wx
  delete (globalThis as { uni?: unknown }).uni
  vi.resetModules()
})

describe('照片选择', () => {
  it('相册优先使用 chooseMedia 且最多 9 张原图', async () => {
    const chooseMedia = vi.fn(({ success }) => success({
      tempFiles: [
        { tempFilePath: '/tmp/a.jpg' },
        { tempFilePath: '/tmp/b.jpg' },
      ],
    }))
    const chooseImage = vi.fn()
    ;(globalThis as { wx?: unknown }).wx = {
      requirePrivacyAuthorize: ({ success }: { success: () => void }) => success(),
      chooseMedia,
      chooseImage,
    }

    const { choosePhotoPaths, getAlbumSelectionLimit } = await import('@/services/media-picker')
    expect(getAlbumSelectionLimit()).toBe(9)
    await expect(choosePhotoPaths('album')).resolves.toEqual(['/tmp/a.jpg', '/tmp/b.jpg'])
    expect(chooseMedia).toHaveBeenCalledWith(expect.objectContaining({
      count: 9,
      mediaType: ['image'],
      sourceType: ['album'],
      sizeType: ['original'],
    }))
    expect(chooseImage).not.toHaveBeenCalled()
  })

  it('chooseMedia 不可用时降级 chooseImage 并保持 9 张上限', async () => {
    const chooseImage = vi.fn(({ success }) => success({ tempFilePaths: ['/tmp/a.jpg'] }))
    ;(globalThis as { wx?: unknown }).wx = {
      requirePrivacyAuthorize: ({ success }: { success: () => void }) => success(),
      chooseImage,
    }

    const { choosePhotoPaths } = await import('@/services/media-picker')
    await expect(choosePhotoPaths('album')).resolves.toEqual(['/tmp/a.jpg'])
    expect(chooseImage).toHaveBeenCalledWith(expect.objectContaining({
      count: 9,
      sourceType: ['album'],
      sizeType: ['original'],
    }))
  })

  it('chooseMedia 真机异常时自动降级 chooseImage', async () => {
    const chooseMedia = vi.fn(({ fail }) => fail({ errMsg: 'chooseMedia:fail system error' }))
    const chooseImage = vi.fn(({ success }) => success({ tempFilePaths: ['/tmp/fallback.jpg'] }))
    ;(globalThis as { wx?: unknown }).wx = {
      requirePrivacyAuthorize: ({ success }: { success: () => void }) => success(),
      chooseMedia,
      chooseImage,
    }

    const { choosePhotoPaths } = await import('@/services/media-picker')
    await expect(choosePhotoPaths('album')).resolves.toEqual(['/tmp/fallback.jpg'])
    expect(chooseImage).toHaveBeenCalledTimes(1)
  })

  it('用户取消时不重复弹备用选择器', async () => {
    const cancel = { errMsg: 'chooseMedia:fail cancel' }
    const chooseMedia = vi.fn(({ fail }) => fail(cancel))
    const chooseImage = vi.fn()
    ;(globalThis as { wx?: unknown }).wx = {
      requirePrivacyAuthorize: ({ success }: { success: () => void }) => success(),
      chooseMedia,
      chooseImage,
    }

    const { choosePhotoPaths } = await import('@/services/media-picker')
    await expect(choosePhotoPaths('album')).rejects.toBe(cancel)
    expect(chooseImage).not.toHaveBeenCalled()
  })

  it('最终失败时保留微信真实 errMsg 便于定位', async () => {
    const chooseMedia = vi.fn(({ fail }) => fail({ errMsg: 'chooseMedia:fail system error' }))
    const chooseImage = vi.fn(({ fail }) => fail({ errMsg: 'chooseImage:fail no permission' }))
    ;(globalThis as { wx?: unknown }).wx = {
      requirePrivacyAuthorize: ({ success }: { success: () => void }) => success(),
      chooseMedia,
      chooseImage,
    }

    const { choosePhotoPaths } = await import('@/services/media-picker')
    await expect(choosePhotoPaths('album')).rejects.toThrow('相册打开失败：chooseImage:fail no permission')
  })
})
