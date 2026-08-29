import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  delete (globalThis as { wx?: unknown }).wx
  delete (globalThis as { uni?: unknown }).uni
  vi.resetModules()
})

describe('照片选择', () => {
  it('相册默认选择压缩图，不锁定微信原图勾选', async () => {
    const chooseImage = vi.fn(({ success }) => success({ tempFilePaths: ['/tmp/a.jpg', '/tmp/b.jpg'] }))
    ;(globalThis as { wx?: unknown }).wx = {
      requirePrivacyAuthorize: ({ success }: { success: () => void }) => success(),
      getSystemInfoSync: () => ({ SDKVersion: '3.2.0' }),
      chooseImage,
    }

    const { choosePhotoPaths } = await import('@/services/media-picker')
    await expect(choosePhotoPaths('album')).resolves.toEqual(['/tmp/a.jpg', '/tmp/b.jpg'])
    expect(chooseImage).toHaveBeenCalledWith(expect.objectContaining({
      count: 20,
      sourceType: ['album'],
      sizeType: ['compressed'],
    }))
  })
})
