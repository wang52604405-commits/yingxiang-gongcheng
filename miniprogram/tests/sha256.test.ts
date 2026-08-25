import { afterEach, describe, expect, it, vi } from 'vitest'
import { hashFileInChunks, readFileChunk, readFilePrefix, sha256Hex } from '@/services/sha256'

describe('客户端 SHA-256', () => {
  afterEach(() => { delete (globalThis as any).wx })

  it('与标准测试向量一致', () => {
    expect(sha256Hex(new TextEncoder().encode('abc').buffer)).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
  })

  it('原图按多个分块增量读取，跨 64 字节边界结果不变', async () => {
    const data = Uint8Array.from({ length: 64 * 3 + 17 }, (_, index) => (index * 37) % 256)
    const read = vi.fn(({ arrayBuffer, length, position, success }: any) => {
      const bytesRead = Math.min(length, Math.max(0, data.length - position))
      new Uint8Array(arrayBuffer).set(data.subarray(position, position + bytesRead))
      success({ bytesRead, arrayBuffer })
    })
    ;(globalThis as any).wx = { getFileSystemManager: () => ({
      open: ({ success }: any) => success({ fd: 7 }),
      read,
      close: ({ success }: any) => success({}),
    }) }
    await expect(hashFileInChunks('/user/large.jpg', 64)).resolves.toBe(sha256Hex(data.buffer))
    expect(read).toHaveBeenCalledTimes(5)
    expect(read.mock.calls.every(([options]) => options.length === 64)).toBe(true)
  })

  it('EXIF 辅读取最多获取指定文件头，不整块读取大原图', async () => {
    const data = new Uint8Array(1_024)
    const read = vi.fn(({ arrayBuffer, length, success }: any) => success({ bytesRead: length, arrayBuffer }))
    ;(globalThis as any).wx = { getFileSystemManager: () => ({
      open: ({ success }: any) => success({ fd: 8 }),
      read,
      close: ({ success }: any) => success({}),
    }) }
    const prefix = await readFilePrefix('/user/50mb.jpg', 256)
    expect(prefix.byteLength).toBe(256)
    expect(read).toHaveBeenCalledWith(expect.objectContaining({ length: 256, position: 0 }))
    void data
  })

  it('分片上传只读取指定 4MiB 区间，不把整张大图载入内存', async () => {
    const read = vi.fn(({ arrayBuffer, length, position, success }: any) => success({ bytesRead: length, arrayBuffer }))
    ;(globalThis as any).wx = { getFileSystemManager: () => ({
      open: ({ success }: any) => success({ fd: 9 }),
      read,
      close: ({ success }: any) => success({}),
    }) }
    const chunk = await readFileChunk('/user/50mb.png', 8 * 1024 * 1024, 4 * 1024 * 1024)
    expect(chunk.byteLength).toBe(4 * 1024 * 1024)
    expect(read).toHaveBeenCalledTimes(1)
    expect(read).toHaveBeenCalledWith(expect.objectContaining({ position: 8 * 1024 * 1024, length: 4 * 1024 * 1024 }))
  })
})
