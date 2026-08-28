import { describe, expect, it, vi } from 'vitest'
import {
  downloadServerPreview,
  normalizeOrientation,
  parseJpegExif,
  persistOriginalSource,
  persistPreparedPreview,
  preparePreview,
  type CompressionAdapter,
} from '@/services/image-compression'

function jpegWithExif(): ArrayBuffer {
  const tiffLength = 76
  const bytes = new Uint8Array(2 + 2 + 2 + 6 + tiffLength + 2)
  bytes.set([0xff, 0xd8, 0xff, 0xe1], 0)
  const segmentLength = 2 + 6 + tiffLength
  bytes[4] = segmentLength >> 8
  bytes[5] = segmentLength & 0xff
  bytes.set([0x45, 0x78, 0x69, 0x66, 0, 0], 6)
  const tiff = 12
  bytes.set([0x49, 0x49, 0x2a, 0x00, 0x08, 0x00, 0x00, 0x00], tiff)
  const view = new DataView(bytes.buffer)
  const ifd0 = tiff + 8
  view.setUint16(ifd0, 2, true)
  let entry = ifd0 + 2
  view.setUint16(entry, 0x0112, true); view.setUint16(entry + 2, 3, true); view.setUint32(entry + 4, 1, true); view.setUint16(entry + 8, 6, true)
  entry += 12
  view.setUint16(entry, 0x8769, true); view.setUint16(entry + 2, 4, true); view.setUint32(entry + 4, 1, true); view.setUint32(entry + 8, 38, true)
  const exifIfd = tiff + 38
  view.setUint16(exifIfd, 1, true)
  entry = exifIfd + 2
  view.setUint16(entry, 0x9003, true); view.setUint16(entry + 2, 2, true); view.setUint32(entry + 4, 20, true); view.setUint32(entry + 8, 56, true)
  bytes.set(new TextEncoder().encode('2026:08:25 09:41:00\0'), tiff + 56)
  bytes.set([0xff, 0xd9], bytes.length - 2)
  return bytes.buffer
}

describe('原图安全落盘与 JPEG 本机预览', () => {
  it('从生成预览前的 JPEG 读取 DateTimeOriginal 与 1..8 方向值', () => {
    const metadata = parseJpegExif(jpegWithExif())
    expect(metadata.orientation).toBe(6)
    const date = new Date(metadata.capturedAt!)
    expect([date.getFullYear(), date.getMonth() + 1, date.getDate(), date.getHours(), date.getMinutes()]).toEqual([2026, 8, 25, 9, 41])
    expect(normalizeOrientation('right')).toBe(6)
    expect(normalizeOrientation('left-mirrored')).toBe(5)
  })

  it('第一步原样保存原图，PNG 不会伪装成 JPEG', async () => {
    const persist = vi.fn(async () => '/user/original.bin')
    const adapter: CompressionAdapter = {
      getImageInfo: async () => ({ path: '/user/original.bin', width: 4_000, height: 3_000, orientation: 'up', type: 'png' }),
      renderJpeg: async (_path, dimensions, quality) => `${dimensions.width}-${quality}`,
      getFileSize: async (path) => path === '/user/original.bin' ? 8_000_000 : Number(path.split('-').at(-1)) * 2_000,
      persist,
    }
    const original = await persistOriginalSource('/tmp/IMG_20260825.png', adapter)
    expect(persist).toHaveBeenNthCalledWith(1, '/tmp/IMG_20260825.png')
    expect(original).toEqual({ originalPath: '/user/original.bin', originalSize: 8_000_000, originalFilename: 'IMG_20260825.png' })
    const preview = await preparePreview(original.originalPath, original.originalFilename, '2026-08-25T01:41:00Z', adapter)
    expect(preview.originalMimeType).toBe('image/png')
    expect(preview.previewTempPath.endsWith('-51')).toBe(true)
    expect(preview.previewSize).toBe(102_000)
  })

  it('最低质量仍超限时缩边 15%，保存后再次执行 100KB 硬检查', async () => {
    const sizes = new Map<string, number>()
    const remove = vi.fn(async () => undefined)
    const adapter: CompressionAdapter = {
      getImageInfo: async () => ({ path: '/user/original.jpg', width: 1_920, height: 1_440, orientation: 1, type: 'jpg' }),
      renderJpeg: async (_path, dimensions, quality) => {
        const key = `${dimensions.width}-${quality}`
        sizes.set(key, dimensions.width === 1_920 ? 130_000 : quality * 1_500)
        return key
      },
      getFileSize: async (path) => path.startsWith('/user/preview') ? 102_401 : sizes.get(path)!,
      persist: async () => '/user/preview.jpg',
      remove,
    }
    const prepared = await preparePreview('/user/original.jpg', 'original.jpg', '2026-08-25T01:41:00Z', adapter)
    expect(prepared.previewWidth).toBe(1_632)
    await expect(persistPreparedPreview(prepared, adapter)).rejects.toThrow('超过 100KB')
    expect(remove).toHaveBeenCalledWith('/user/preview.jpg')
    expect(remove).not.toHaveBeenCalledWith('/user/original.jpg')
  })

  it('服务器生成的预览再次校验不超过 100KB 后才持久保存', async () => {
    ;(globalThis as any).uni = {
      downloadFile: ({ success }: any) => success({ statusCode: 200, tempFilePath: '/tmp/server-preview.jpg' }),
    }
    const adapter: CompressionAdapter = {
      getImageInfo: async () => ({ path: '', width: 0, height: 0, orientation: 1 }),
      renderJpeg: async () => '',
      getFileSize: async (path) => path.startsWith('/tmp/') ? 92_000 : 91_500,
      persist: async () => '/user/server-preview.jpg',
    }
    await expect(downloadServerPreview('https://api.example.test/preview', adapter)).resolves.toEqual({
      previewPath: '/user/server-preview.jpg',
      previewSize: 91_500,
    })
  })
})
