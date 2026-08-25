import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LocalBatch, LocalPhoto, UploadDraft } from '@/types/domain'

const mocks = vi.hoisted(() => ({
  stageOriginal: vi.fn(),
  loadQueue: vi.fn(),
  persistSnapshot: vi.fn(),
  clearOriginalWal: vi.fn(),
  uploadPhotoInChunks: vi.fn(),
  getSourceFileSize: vi.fn(),
  preparePreview: vi.fn(),
  persistPreparedPreview: vi.fn(),
  hashFile: vi.fn(),
  batch: vi.fn(),
  createBatch: vi.fn(),
  uploadPhoto: vi.fn(),
  analyzeBatch: vi.fn(),
  commitBatch: vi.fn(),
  assignBatch: vi.fn(),
}))

vi.mock('@/services/image-compression', () => ({
  getSourceFileSize: mocks.getSourceFileSize,
  preparePreview: mocks.preparePreview,
  persistPreparedPreview: mocks.persistPreparedPreview,
}))
vi.mock('@/services/sha256', () => ({ hashFile: mocks.hashFile }))
vi.mock('@/services/queue-storage', () => ({ queueFileStore: {
  stageOriginal: mocks.stageOriginal,
  load: mocks.loadQueue,
  persistSnapshot: mocks.persistSnapshot,
  clearOriginalWal: mocks.clearOriginalWal,
} }))
vi.mock('@/services/chunk-upload', () => ({
  UploadPausedError: class UploadPausedError extends Error {},
  uploadPhotoInChunks: mocks.uploadPhotoInChunks,
}))
vi.mock('@/api/mobile', () => ({ mobileApi: {
  batch: mocks.batch,
  createBatch: mocks.createBatch,
  uploadPhoto: mocks.uploadPhoto,
  analyzeBatch: mocks.analyzeBatch,
  commitBatch: mocks.commitBatch,
  assignBatch: mocks.assignBatch,
} }))

const draft: UploadDraft = {
  project_id: 'YNLQ',
  scope: 'engineering',
  category: 'construction',
  mode: 'direct',
  assignment: { unit_code: 'YNLQ-DY-001', unit_name: '进口段', process_name: '钢筋安装' },
}

function installPlatform(storage: Map<string, any>, online: boolean, unlink = vi.fn()) {
  mocks.loadQueue.mockImplementation((owner: string) => storage.get(`engineering-image:queue:v2:account:${owner}`) || { owner_account_id: owner, photos: [], batches: [] })
  mocks.persistSnapshot.mockImplementation((owner: string, photos: LocalPhoto[], batches: LocalBatch[]) => {
    storage.set(`engineering-image:queue:v2:account:${owner}`, { owner_account_id: owner, photos: JSON.parse(JSON.stringify(photos)), batches: JSON.parse(JSON.stringify(batches)) })
  })
  ;(globalThis as any).uni = {
    getStorageSync: (key: string) => storage.get(key),
    setStorageSync: (key: string, value: unknown) => storage.set(key, value),
    removeStorageSync: (key: string) => storage.delete(key),
    getNetworkType: ({ success }: any) => success({ networkType: online ? 'wifi' : 'none' }),
    onNetworkStatusChange: vi.fn(),
  }
  ;(globalThis as any).wx = {
    env: { USER_DATA_PATH: '/user' },
    getFileSystemManager: () => ({ unlink: ({ filePath, success }: any) => { unlink(filePath); success({}) } }),
  }
  return unlink
}

function preparedPreview() {
  return {
    originalMimeType: 'image/jpeg' as const,
    previewTempPath: '/tmp/preview.jpg',
    previewSize: 90_000,
    previewWidth: 1_600,
    previewHeight: 1_200,
    width: 4_000,
    height: 3_000,
    orientation: 1,
    capturedAt: '2026-08-25T01:00:00Z',
  }
}

function localPhoto(owner: string, id: string): LocalPhoto {
  return {
    owner_account_id: owner,
    photo_uuid: id,
    client_batch_id: `batch-${owner}`,
    remote_batch_id: '18',
    original_path: `/user/${owner}-original.jpg`,
    original_size: 8_000_000,
    original_sha256: 'b'.repeat(64),
    original_filename: `${owner}.jpg`,
    original_mime_type: 'image/jpeg',
    preview_path: `/user/${owner}-preview.jpg`,
    preview_size: 90_000,
    preview_sha256: 'c'.repeat(64),
    preview_width: 1_600,
    preview_height: 1_200,
    width: 4_000,
    height: 3_000,
    orientation: 1,
    client_captured_at: '2026-08-25T01:00:00Z',
    title: '模板验收',
    photo_date: '2026-08-25',
    draft,
    status: 'desktop_pending',
    progress: 100,
    created_at: '2026-08-25T01:00:00Z',
    updated_at: '2026-08-25T01:00:00Z',
  }
}

function localBatch(photo: LocalPhoto): LocalBatch {
  return {
    owner_account_id: photo.owner_account_id,
    client_batch_id: photo.client_batch_id,
    remote_batch_id: '18',
    draft,
    photo_uuids: [photo.photo_uuid],
    committed: true,
    analyzed: false,
    created_at: photo.created_at,
  }
}

describe('原图优先落盘与账号隔离队列', () => {
  beforeEach(() => {
    vi.resetModules()
    Object.values(mocks).forEach((mock) => mock.mockReset())
    mocks.preparePreview.mockResolvedValue(preparedPreview())
    mocks.getSourceFileSize.mockResolvedValue(8_000_000)
    mocks.persistPreparedPreview.mockResolvedValue({ ...preparedPreview(), previewPath: '/user/preview.jpg' })
    mocks.hashFile.mockResolvedValueOnce('a'.repeat(64)).mockResolvedValueOnce('c'.repeat(64))
  })

  it('批量第 N 张失败时，第一张原图已写恢复记录且仍属于先落盘批次', async () => {
    const storage = new Map<string, any>()
    installPlatform(storage, false)
    mocks.stageOriginal
      .mockResolvedValueOnce({ originalPath: '/user/original-1.jpg', originalSize: 8_000_000, originalFilename: '1.jpg' })
      .mockRejectedValueOnce(new Error('第二张无法保存'))

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await expect(queueRuntime.enqueue(['/tmp/1.jpg', '/tmp/2.jpg'], draft)).rejects.toThrow('已有 1 张原图安全保存')
    expect(queueRuntime.state.batches).toHaveLength(1)
    expect(queueRuntime.state.photos).toHaveLength(1)
    expect(queueRuntime.state.batches[0].photo_uuids).toEqual([queueRuntime.state.photos[0].photo_uuid])
    expect(queueRuntime.state.photos[0]).toMatchObject({ owner_account_id: '32', original_path: '/user/original-1.jpg', preview_path: '/user/preview.jpg' })
  })

  it('预览生成失败绝不删除已经持久化的相机原图，并留下可重试项', async () => {
    const storage = new Map<string, any>()
    const unlink = installPlatform(storage, false)
    mocks.stageOriginal.mockResolvedValue({ originalPath: '/user/only-original.jpg', originalSize: 9_000_000, originalFilename: 'camera.jpg' })
    mocks.preparePreview.mockRejectedValue(new Error('预览生成失败'))

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.enqueue(['/tmp/camera.jpg'], draft)
    expect(queueRuntime.state.photos[0]).toMatchObject({ original_path: '/user/only-original.jpg', preview_path: '', status: 'failed', preparation_pending: true })
    expect(queueRuntime.state.photos[0].error).toContain('原图已安全保存')
    expect(unlink).not.toHaveBeenCalledWith('/user/only-original.jpg')
  })

  it('159.9MB 队列加新原图会在复制前拒绝，且不生成恢复记录', async () => {
    const existing = localPhoto('32', 'existing')
    existing.status = 'failed'
    existing.original_size = Math.floor(159.9 * 1024 * 1024)
    existing.preview_path = ''
    existing.preview_size = 0
    existing.preparation_pending = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [existing], batches: [] },
    ]])
    installPlatform(storage, false)
    mocks.getSourceFileSize.mockResolvedValue(10_000)

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await expect(queueRuntime.enqueue(['/tmp/new.jpg'], draft)).rejects.toThrow('将超过 160MB')
    expect(mocks.stageOriginal).not.toHaveBeenCalled()
    expect(queueRuntime.state.photos.map((photo) => photo.photo_uuid)).toEqual(['existing'])
    expect(queueRuntime.state.batches).toHaveLength(0)
  })

  it('电脑已归档时只释放原图，100KB 本机预览继续保留', async () => {
    const photo = localPhoto('32', 'photo-32')
    const batch = localBatch(photo)
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    const unlink = installPlatform(storage, true)
    mocks.batch.mockResolvedValue({ ok: true, batch_id: '18', status: 'desktop_imported', photos: [{ photo_uuid: photo.photo_uuid, status: 'desktop_imported', match_candidates: [] }] })

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    expect(unlink).toHaveBeenCalledWith('/user/32-original.jpg')
    expect(unlink).not.toHaveBeenCalledWith('/user/32-preview.jpg')
    expect(queueRuntime.state.photos[0]).toMatchObject({ status: 'desktop_imported', original_path: '', original_removed: true, preview_path: '/user/32-preview.jpg' })
    expect(queueRuntime.queueBytes.value).toBe(90_000)
  })

  it('上传只发送原图路径，server_saved 后立即释放原图但保留预览', async () => {
    const photo = localPhoto('32', 'photo-upload')
    photo.status = 'local_ready'
    photo.remote_batch_id = undefined
    photo.progress = 0
    const batch = localBatch(photo)
    batch.remote_batch_id = undefined
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    const unlink = installPlatform(storage, true)
    mocks.createBatch.mockResolvedValue({ ok: true, batch_id: '19' })
    mocks.uploadPhoto.mockResolvedValue({ ok: true, photo: { status: 'server_saved' } })
    mocks.commitBatch.mockResolvedValue({ ok: true })

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    expect(mocks.uploadPhoto).toHaveBeenCalledWith('19', '/user/32-original.jpg', expect.objectContaining({
      sha256: 'b'.repeat(64),
      original_size_bytes: 8_000_000,
      original_filename: '32.jpg',
      original_mime_type: 'image/jpeg',
    }), expect.any(Function))
    const metadata = mocks.uploadPhoto.mock.calls[0][2]
    expect(metadata).not.toHaveProperty('preview_sha256')
    expect(unlink).toHaveBeenCalledWith('/user/32-original.jpg')
    expect(unlink).not.toHaveBeenCalledWith('/user/32-preview.jpg')
    expect(queueRuntime.state.photos[0]).toMatchObject({ status: 'desktop_pending', original_path: '', preview_path: '/user/32-preview.jpg' })
  })

  it('超过 8MiB 的原图不调用 uploadFile，改走可持久化的 4MiB 分片路径', async () => {
    const photo = localPhoto('32', 'photo-large')
    photo.status = 'local_ready'
    photo.original_size = 12 * 1024 * 1024
    photo.remote_batch_id = undefined
    const batch = localBatch(photo)
    batch.remote_batch_id = undefined
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    installPlatform(storage, true)
    mocks.createBatch.mockResolvedValue({ ok: true, batch_id: 'large-batch' })
    mocks.commitBatch.mockResolvedValue({ ok: true })
    mocks.uploadPhotoInChunks.mockImplementation(async (options: any) => {
      options.onCheckpoint({ uploadId: 'upload-large', chunkSize: 4 * 1024 * 1024, totalChunks: 3, uploadedChunks: [0, 1, 2] })
      options.onProgress(100)
      return { ok: true }
    })

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    expect(mocks.uploadPhoto).not.toHaveBeenCalled()
    expect(mocks.uploadPhotoInChunks).toHaveBeenCalledWith(expect.objectContaining({
      batchId: 'large-batch',
      filePath: '/user/32-original.jpg',
      metadata: expect.objectContaining({ photo_uuid: 'photo-large', original_size_bytes: 12 * 1024 * 1024 }),
    }))
    expect(queueRuntime.state.photos[0]).toMatchObject({
      upload_mode: 'chunked',
      chunk_upload_id: 'upload-large',
      uploaded_chunks: [0, 1, 2],
      status: 'desktop_pending',
    })
  })

  it('上传遇到 401 时暂停并重验同账号，恢复后用同一 photo_uuid 幂等续传', async () => {
    const photo = localPhoto('32', 'stable-photo-uuid')
    photo.status = 'local_ready'
    photo.remote_batch_id = undefined
    photo.progress = 0
    const batch = localBatch(photo)
    batch.remote_batch_id = undefined
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    installPlatform(storage, true)
    mocks.createBatch.mockResolvedValue({ ok: true, batch_id: '20' })
    mocks.commitBatch.mockResolvedValue({ ok: true })

    const { queueRuntime } = await import('@/services/queue-runtime')
    const { ApiError } = await import('@/api/client')
    const { registerAuthExpiredHandler } = await import('@/services/auth-expiry-coordinator')
    mocks.uploadPhoto
      .mockRejectedValueOnce(new ApiError('登录已过期', 'token_expired', false, 401))
      .mockResolvedValueOnce({ ok: true, photo: { status: 'server_saved' } })
    registerAuthExpiredHandler(async (owner) => {
      queueRuntime.clearOwner()
      queueRuntime.setOwner(owner)
      queueRuntime.recoverAuthFailures()
      await queueRuntime.resume('manual')
    })
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    await vi.waitFor(() => expect(queueRuntime.state.photos[0]?.status).toBe('desktop_pending'))
    expect(mocks.createBatch).toHaveBeenCalledTimes(1)
    expect(mocks.uploadPhoto.mock.calls.map((call) => call[2].photo_uuid)).toEqual(['stable-photo-uuid', 'stable-photo-uuid'])
    expect(queueRuntime.state.photos).toHaveLength(1)
    expect(queueRuntime.state.photos[0]).toMatchObject({ status: 'desktop_pending', original_path: '', preview_path: '/user/32-preview.jpg' })
  })

  it('OCR 只发快速受理请求，结果在前台后续轮询批次取得', async () => {
    const photo = localPhoto('32', 'photo-analyze')
    photo.status = 'server_saved'
    photo.original_path = ''
    photo.original_removed = true
    photo.draft = { ...draft, mode: 'auto', assignment: undefined }
    const batch = localBatch(photo)
    batch.draft = photo.draft
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    installPlatform(storage, true)
    mocks.batch.mockResolvedValueOnce({ ok: true, batch_id: '18', status: 'analyzing', photos: [{ photo_uuid: photo.photo_uuid, status: 'server_saved' }] })
    mocks.analyzeBatch.mockResolvedValue({ ok: true, job: { job_id: 'job-18', status: 'queued' } })

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    expect(mocks.analyzeBatch).toHaveBeenCalledTimes(1)
    expect(mocks.batch).toHaveBeenCalledTimes(1)
    expect(queueRuntime.state.batches[0]).toMatchObject({ analysis_requested: true, analysis_job_id: 'job-18', analyzed: false })
    expect(queueRuntime.state.photos[0].status).toBe('analyzing')

    mocks.batch.mockResolvedValueOnce({ ok: true, batch_id: '18', status: 'needs_review', photos: [{ photo_uuid: photo.photo_uuid, status: 'needs_review', match_candidates: [] }] })
    await queueRuntime.resume('manual')
    expect(mocks.analyzeBatch).toHaveBeenCalledTimes(1)
    expect(queueRuntime.state.photos[0].status).toBe('needs_review')
    expect(queueRuntime.state.batches[0].analyzed).toBe(true)
  })

  it('大图分片遇到 401 后重验同账号，并用同一 UUID 继续服务器断点', async () => {
    const photo = localPhoto('32', 'large-auth-uuid')
    photo.status = 'local_ready'
    photo.original_size = 16 * 1024 * 1024
    photo.remote_batch_id = undefined
    photo.uploaded_chunks = [0]
    const batch = localBatch(photo)
    batch.remote_batch_id = undefined
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    installPlatform(storage, true)
    mocks.createBatch.mockResolvedValue({ ok: true, batch_id: 'large-auth-batch' })
    mocks.commitBatch.mockResolvedValue({ ok: true })

    const { ApiError } = await import('@/api/client')
    mocks.uploadPhotoInChunks
      .mockRejectedValueOnce(new ApiError('登录已过期', 'AUTH_EXPIRED', false, 401))
      .mockImplementationOnce(async (options: any) => {
        options.onCheckpoint({ uploadId: 'same-upload', chunkSize: 4 * 1024 * 1024, totalChunks: 4, uploadedChunks: [0, 1, 2, 3] })
        return { ok: true }
      })
    const { queueRuntime } = await import('@/services/queue-runtime')
    const { registerAuthExpiredHandler } = await import('@/services/auth-expiry-coordinator')
    registerAuthExpiredHandler(async (owner) => {
      queueRuntime.clearOwner()
      queueRuntime.setOwner(owner)
      queueRuntime.recoverAuthFailures()
      await queueRuntime.resume('manual')
    })
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    await vi.waitFor(() => expect(queueRuntime.state.photos[0]?.status).toBe('desktop_pending'))
    expect(mocks.uploadPhotoInChunks).toHaveBeenCalledTimes(2)
    expect(mocks.uploadPhotoInChunks.mock.calls.map((call) => call[0].metadata.photo_uuid)).toEqual(['large-auth-uuid', 'large-auth-uuid'])
    expect(mocks.uploadPhotoInChunks.mock.calls[1][0].previousUploadedChunks).toEqual([0])
  })

  it('切换账号只切换视图和上传命名空间，不混看也不删除上一账号队列', async () => {
    const photoA = localPhoto('A', 'photo-a')
    const photoB = localPhoto('B', 'photo-b')
    const storage = new Map<string, any>([
      ['engineering-image:queue:v2:account:A', { owner_account_id: 'A', photos: [photoA], batches: [localBatch(photoA)] }],
      ['engineering-image:queue:v2:account:B', { owner_account_id: 'B', photos: [photoB], batches: [localBatch(photoB)] }],
    ])
    const unlink = installPlatform(storage, false)
    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('A')
    expect(queueRuntime.state.photos.map((photo) => photo.photo_uuid)).toEqual(['photo-a'])
    queueRuntime.setOwner('B')
    expect(queueRuntime.state.photos.map((photo) => photo.photo_uuid)).toEqual(['photo-b'])
    queueRuntime.clearOwner()
    expect(queueRuntime.state.photos).toHaveLength(0)
    expect(storage.get('engineering-image:queue:v2:account:A').photos[0].photo_uuid).toBe('photo-a')
    expect(unlink).not.toHaveBeenCalled()
  })
})
