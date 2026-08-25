import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PhotoUploadMetadata } from '@/api/contracts'
import { ApiError } from '@/api/client'

const mocks = vi.hoisted(() => ({
  init: vi.fn(),
  query: vi.fn(),
  upload: vi.fn(),
  finalize: vi.fn(),
  read: vi.fn(),
  sha: vi.fn(() => 'f'.repeat(64)),
}))

vi.mock('@/api/mobile', () => ({ mobileApi: {
  initChunkedUpload: mocks.init,
  chunkedUpload: mocks.query,
  uploadChunk: mocks.upload,
  finalizeChunkedUpload: mocks.finalize,
} }))
vi.mock('@/services/sha256', () => ({ readFileChunk: mocks.read, sha256Hex: mocks.sha }))

const metadata: PhotoUploadMetadata = {
  photo_uuid: 'large-stable-uuid',
  client_captured_at: '2026-08-25T01:00:00Z',
  orientation: 1,
  width: 6_000,
  height: 4_000,
  sha256: 'a'.repeat(64),
  original_size_bytes: 10 * 1024 * 1024 + 17,
  original_filename: 'large.png',
  original_mime_type: 'image/png',
  title: '大图断点测试',
  photo_date: '2026-08-25',
}

function uploadState(uploaded: number[], status = 'uploading') {
  return {
    upload_id: 'upload-1',
    batch_id: '18',
    photo_uuid: metadata.photo_uuid,
    status,
    total_size_bytes: metadata.original_size_bytes,
    chunk_size_bytes: 4 * 1024 * 1024,
    total_chunks: 3,
    uploaded_chunks: uploaded,
  }
}

describe('大原图 4MiB 分片断点续传', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset())
    mocks.sha.mockReturnValue('f'.repeat(64))
    mocks.read.mockImplementation((_path, _position, length) => Promise.resolve(new ArrayBuffer(length)))
    mocks.init.mockResolvedValue({ ok: true, idempotent: false, upload: uploadState([]) })
    mocks.query.mockResolvedValue({ ok: true, upload: uploadState([]) })
    mocks.upload.mockImplementation((_batch, _uuid, index) => Promise.resolve({ ok: true, idempotent: false, uploaded_chunks: [index] }))
    mocks.finalize.mockResolvedValue({ ok: true, photo: { photo_uuid: metadata.photo_uuid, status: 'server_saved' } })
  })

  it('本机旧记录显示全片但服务器新会话为空时，以服务器为准完整重传', async () => {
    const { uploadPhotoInChunks } = await import('@/services/chunk-upload')
    await uploadPhotoInChunks({
      batchId: '18',
      filePath: '/user/large.png',
      metadata,
      previousUploadedChunks: [0, 1, 2],
      shouldContinue: () => true,
      onCheckpoint: vi.fn(),
    })

    expect(mocks.upload.mock.calls.map((call) => call[2])).toEqual([0, 1, 2])
    expect(mocks.read.mock.calls.map((call) => [call[1], call[2]])).toEqual([
      [0, 4 * 1024 * 1024],
      [4 * 1024 * 1024, 4 * 1024 * 1024],
      [8 * 1024 * 1024, 2 * 1024 * 1024 + 17],
    ])
    expect(mocks.finalize).toHaveBeenCalledWith('18', metadata, 3)
  })

  it('服务器已收分片与重复片会被跳过，只补缺片后 finalize', async () => {
    mocks.query.mockResolvedValue({ ok: true, upload: uploadState([0, 2]) })
    mocks.upload.mockResolvedValue({ ok: true, idempotent: true, uploaded_chunks: [0, 1, 2] })
    const checkpoints: number[][] = []
    const { uploadPhotoInChunks } = await import('@/services/chunk-upload')
    await uploadPhotoInChunks({
      batchId: '18', filePath: '/user/large.png', metadata, shouldContinue: () => true,
      onCheckpoint: (checkpoint) => checkpoints.push(checkpoint.uploadedChunks),
    })

    expect(mocks.upload).toHaveBeenCalledTimes(1)
    expect(mocks.upload.mock.calls[0][2]).toBe(1)
    expect(checkpoints.at(-1)).toEqual([0, 1, 2])
  })

  it('切后台后停止下一片，回前台查询服务器进度并从缺片继续', async () => {
    let foreground = true
    mocks.upload.mockImplementation((_batch, _uuid, index) => {
      foreground = false
      return Promise.resolve({ ok: true, idempotent: false, uploaded_chunks: [index] })
    })
    const { UploadPausedError, uploadPhotoInChunks } = await import('@/services/chunk-upload')
    await expect(uploadPhotoInChunks({
      batchId: '18', filePath: '/user/large.png', metadata, shouldContinue: () => foreground, onCheckpoint: vi.fn(),
    })).rejects.toBeInstanceOf(UploadPausedError)
    expect(mocks.upload.mock.calls.map((call) => call[2])).toEqual([0])

    foreground = true
    mocks.upload.mockClear()
    mocks.query.mockResolvedValue({ ok: true, upload: uploadState([0]) })
    mocks.upload.mockImplementation((_batch, _uuid, index) => Promise.resolve({ ok: true, idempotent: false, uploaded_chunks: [0, index] }))
    await uploadPhotoInChunks({
      batchId: '18', filePath: '/user/large.png', metadata, previousUploadedChunks: [0], shouldContinue: () => foreground, onCheckpoint: vi.fn(),
    })
    expect(mocks.upload.mock.calls.map((call) => call[2])).toEqual([1, 2])
  })

  it('401 后保留同一 UUID；重新登录调用时从服务器已收片继续且不重复', async () => {
    mocks.init.mockRejectedValueOnce(new ApiError('登录已过期', 'AUTH_EXPIRED', false, 401))
    const { uploadPhotoInChunks } = await import('@/services/chunk-upload')
    const options = { batchId: '18', filePath: '/user/large.png', metadata, shouldContinue: () => true, onCheckpoint: vi.fn() }
    await expect(uploadPhotoInChunks(options)).rejects.toMatchObject({ statusCode: 401 })

    mocks.query.mockResolvedValue({ ok: true, upload: uploadState([0, 1]) })
    await uploadPhotoInChunks(options)
    expect(mocks.init.mock.calls.map((call) => call[1].photo_uuid)).toEqual([metadata.photo_uuid, metadata.photo_uuid])
    expect(mocks.upload.mock.calls.map((call) => call[2])).toEqual([2])
  })

  it('init 表明已 finalize 时直接按幂等成功处理，不再依赖已清理的 GET 会话', async () => {
    mocks.init.mockResolvedValue({ ok: true, idempotent: true, upload: uploadState([0, 1, 2], 'completed') })
    const { uploadPhotoInChunks } = await import('@/services/chunk-upload')
    await expect(uploadPhotoInChunks({
      batchId: '18', filePath: '/user/large.png', metadata, shouldContinue: () => true, onCheckpoint: vi.fn(),
    })).resolves.toBeTruthy()
    expect(mocks.query).not.toHaveBeenCalled()
    expect(mocks.upload).not.toHaveBeenCalled()
    expect(mocks.finalize).not.toHaveBeenCalled()
  })

  it('init 后 GET 恰逢 finalize 清理而返回 404，会再次 init 并按已完成幂等成功', async () => {
    mocks.init
      .mockResolvedValueOnce({ ok: true, idempotent: true, upload: uploadState([], 'uploading') })
      .mockResolvedValueOnce({ ok: true, idempotent: true, upload: uploadState([0, 1, 2], 'completed') })
    mocks.query.mockRejectedValue(new ApiError('会话已清理', 'UPLOAD_NOT_FOUND', true, 404))
    const { uploadPhotoInChunks } = await import('@/services/chunk-upload')
    await expect(uploadPhotoInChunks({
      batchId: '18', filePath: '/user/large.png', metadata, shouldContinue: () => true, onCheckpoint: vi.fn(),
    })).resolves.toBeTruthy()
    expect(mocks.init).toHaveBeenCalledTimes(2)
    expect(mocks.upload).not.toHaveBeenCalled()
    expect(mocks.finalize).not.toHaveBeenCalled()
  })
})
