import { describe, expect, it, vi } from 'vitest'
import { mobileApi } from '@/api/mobile'
import type { PhotoUploadMetadata } from '@/api/contracts'

describe('服务端分片 API 精确契约', () => {
  it('init/query/PUT/finalize 使用锁定路由，init 携带归档规格并由会话约束 finalize', async () => {
    const metadata: PhotoUploadMetadata = {
      photo_uuid: 'photo-contract',
      client_captured_at: '2026-08-25T01:00:00Z',
      orientation: 6,
      width: 6_000,
      height: 4_000,
      sha256: 'a'.repeat(64),
      original_size_bytes: 1_048_576,
      original_filename: 'IMG.jpg',
      original_mime_type: 'image/jpeg',
      title: '钢筋检查',
      photo_date: '2026-08-25',
      capture_source: 'camera',
      transfer_profile: 'jpeg_1m',
    }
    const request = vi.fn((options: any) => {
      if (options.method === 'PUT') {
        options.success({ statusCode: 200, data: { ok: true, idempotent: false, uploaded_chunks: [0] } })
      } else if (options.url.endsWith('/init')) {
        options.success({ statusCode: 200, data: { ok: true, upload: { upload_id: 'u1', batch_id: '18', photo_uuid: metadata.photo_uuid, status: 'uploading', total_size_bytes: metadata.original_size_bytes, chunk_size_bytes: 256 * 1024, total_chunks: 4, uploaded_chunks: [] } } })
      } else if (options.url.endsWith('/finalize')) {
        options.success({ statusCode: 200, data: { ok: true, photo: { photo_uuid: metadata.photo_uuid, status: 'server_saved' }, upload: { upload_id: 'u1', status: 'completed' } } })
      } else {
        options.success({ statusCode: 200, data: { ok: true, upload: { upload_id: 'u1', batch_id: '18', photo_uuid: metadata.photo_uuid, status: 'uploading', total_size_bytes: metadata.original_size_bytes, chunk_size_bytes: 256 * 1024, total_chunks: 4, uploaded_chunks: [0] } } })
      }
    })
    ;(globalThis as any).uni = { getStorageSync: () => 'token', request }

    await mobileApi.initChunkedUpload('18', metadata, 256 * 1024)
    await mobileApi.chunkedUpload('18', metadata.photo_uuid)
    const bytes = new ArrayBuffer(256 * 1024)
    await mobileApi.uploadChunk('18', metadata.photo_uuid, 0, bytes, 'b'.repeat(64))
    await mobileApi.finalizeChunkedUpload('18', metadata, 4)

    const [init, query, chunk, finalize] = request.mock.calls.map(([options]) => options)
    expect(init).toMatchObject({ method: 'POST', timeout: 20_000 })
    expect(init.url).toMatch(/\/batches\/18\/chunked-uploads\/init$/)
    expect(init.data).toEqual({
      photo_uuid: metadata.photo_uuid,
      sha256: metadata.sha256,
      original_size_bytes: metadata.original_size_bytes,
      original_filename: 'IMG.jpg',
      chunk_size_bytes: 256 * 1024,
      total_chunks: 4,
      client_captured_at: metadata.client_captured_at,
      orientation: 6,
      width: 6_000,
      height: 4_000,
      title: '钢筋检查',
      photo_date: '2026-08-25',
      capture_source: 'camera',
      transfer_profile: 'jpeg_1m',
    })
    expect(query.url).toMatch(/\/batches\/18\/chunked-uploads\/photo-contract$/)
    expect(query.method).toBe('GET')
    expect(chunk).toMatchObject({ method: 'PUT', timeout: 55_000, data: bytes })
    expect(chunk.url).toMatch(/\/batches\/18\/chunked-uploads\/photo-contract\/chunks\/0$/)
    expect(chunk.header['X-Chunk-SHA256']).toBe('b'.repeat(64))
    expect(finalize.url).toMatch(/\/batches\/18\/chunked-uploads\/photo-contract\/finalize$/)
    expect(finalize.timeout).toBe(120_000)
    expect(finalize.data).toEqual({ sha256: metadata.sha256, original_size_bytes: metadata.original_size_bytes, total_chunks: 4 })
  })

  it('analyze 只等待快速 202 job，不依赖 OCR 长连接', async () => {
    const request = vi.fn((options: any) => options.success({
      statusCode: 202,
      data: {
        ok: true,
        idempotent: false,
        job: { job_id: 'job-18', status: 'queued' },
        batch: { batch_id: '18', client_batch_id: 'client-18', status: 'analyzing', photos: [] },
      },
    }))
    ;(globalThis as any).uni = { getStorageSync: () => 'token', request }
    await expect(mobileApi.analyzeBatch('18')).resolves.toMatchObject({ job: { job_id: 'job-18', status: 'queued' } })
    expect(request).toHaveBeenCalledWith(expect.objectContaining({
      method: 'POST',
      timeout: 20_000,
      url: expect.stringMatching(/\/batches\/18\/analyze$/),
    }))
  })
})
