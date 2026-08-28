import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LocalBatch, LocalPhoto, UploadDraft } from '@/types/domain'

const mocks = vi.hoisted(() => ({
  stageOriginal: vi.fn(),
  loadQueue: vi.fn(),
  persistSnapshot: vi.fn(),
  clearOriginalWal: vi.fn(),
  uploadPhotoInChunks: vi.fn(),
  getSourceFileSize: vi.fn(),
  inspectOriginalSource: vi.fn(),
  prepareTransferImage: vi.fn(),
  persistPreparedTransfer: vi.fn(),
  preparePreview: vi.fn(),
  persistPreparedPreview: vi.fn(),
  downloadServerPreview: vi.fn(),
  hashFile: vi.fn(),
  batch: vi.fn(),
  createBatch: vi.fn(),
  uploadPhoto: vi.fn(),
  photo: vi.fn(),
  analyzeBatch: vi.fn(),
  commitBatch: vi.fn(),
  assignBatch: vi.fn(),
  updateBatchArchiveInfo: vi.fn(),
}))

vi.mock('@/services/image-compression', () => ({
  getSourceFileSize: mocks.getSourceFileSize,
  inspectOriginalSource: mocks.inspectOriginalSource,
  prepareTransferImage: mocks.prepareTransferImage,
  persistPreparedTransfer: mocks.persistPreparedTransfer,
  preparePreview: mocks.preparePreview,
  persistPreparedPreview: mocks.persistPreparedPreview,
  downloadServerPreview: mocks.downloadServerPreview,
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
  photo: mocks.photo,
  analyzeBatch: mocks.analyzeBatch,
  commitBatch: mocks.commitBatch,
  assignBatch: mocks.assignBatch,
  updateBatchArchiveInfo: mocks.updateBatchArchiveInfo,
} }))

const draft: UploadDraft = {
  project_id: '32:YNLQ',
  project_name: '邯郸市永年区洺河龙泉缓洪工程',
  scope: 'engineering',
  category: 'construction',
  mode: 'direct',
  transfer_profile: 'jpeg_1m',
  assignment: {
    unit_project_code: 'YNLQ-DW-001',
    unit_project_name: '拦河闸单位工程',
    part_code: 'YNLQ-FB-001',
    part_name: '进口段分部工程',
    unit_code: 'YNLQ-DY-001',
    unit_name: '进口段',
    process_name: '钢筋安装',
    process_required: true,
  },
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

function preparedTransfer() {
  return {
    transferTempPath: '/tmp/transfer.jpg',
    transferSize: 900_000,
    transferWidth: 2_560,
    transferHeight: 1_920,
    transferFilename: '32.jpg',
  }
}

function localPhoto(owner: string, id: string): LocalPhoto {
  return {
    owner_account_id: owner,
    photo_uuid: id,
    client_batch_id: `batch-${owner}`,
    remote_batch_id: '18',
    original_path: `/user/${owner}-original.jpg`,
    original_size: 3_000_000,
    original_sha256: 'b'.repeat(64),
    original_filename: `${owner}.jpg`,
    original_mime_type: 'image/jpeg',
    transfer_path: `/user/${owner}-transfer.jpg`,
    transfer_size: 900_000,
    transfer_sha256: 'd'.repeat(64),
    transfer_filename: `${owner}.jpg`,
    transfer_width: 2_560,
    transfer_height: 1_920,
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
    mocks.prepareTransferImage.mockResolvedValue(preparedTransfer())
    mocks.persistPreparedTransfer.mockResolvedValue({ ...preparedTransfer(), transferPath: '/user/transfer.jpg' })
    mocks.inspectOriginalSource.mockResolvedValue({
      originalMimeType: 'image/jpeg',
      width: 4_000,
      height: 3_000,
      orientation: 1,
      capturedAt: '2026-08-25T01:00:00Z',
    })
    mocks.getSourceFileSize.mockResolvedValue(8_000_000)
    mocks.persistPreparedPreview.mockResolvedValue({ ...preparedPreview(), previewPath: '/user/preview.jpg' })
    mocks.downloadServerPreview.mockResolvedValue({ previewPath: '/user/server-preview.jpg', previewSize: 88_000 })
    mocks.hashFile.mockResolvedValueOnce('d'.repeat(64)).mockResolvedValueOnce('c'.repeat(64))
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
    expect(queueRuntime.state.photos[0]).toMatchObject({ owner_account_id: '32', original_path: '', transfer_path: '/user/transfer.jpg', preview_path: '/user/preview.jpg' })
  })

  it('本机预览生成失败时保留暂存原图和 1MiB 归档图等待恢复', async () => {
    const storage = new Map<string, any>()
    const unlink = installPlatform(storage, false)
    mocks.stageOriginal.mockResolvedValue({ originalPath: '/user/only-original.jpg', originalSize: 9_000_000, originalFilename: 'camera.jpg' })
    mocks.preparePreview.mockRejectedValue(new Error('预览生成失败'))

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.enqueue(['/tmp/camera.jpg'], draft)
    expect(queueRuntime.state.photos[0]).toMatchObject({
      original_path: '/user/only-original.jpg',
      transfer_path: '/user/transfer.jpg',
      preview_path: '',
      status: 'failed',
      preparation_pending: true,
    })
    expect(queueRuntime.state.photos[0].error).toContain('预览生成失败')
    expect(unlink).not.toHaveBeenCalledWith('/user/only-original.jpg')
  })

  it('暂存原图可在重试时补齐 100KB 预览，准备完成后才删除大图', async () => {
    const photo = localPhoto('32', 'preview-recovery')
    photo.status = 'failed'
    photo.retry_from = 'local_ready'
    photo.preparation_pending = true
    photo.preview_path = ''
    photo.preview_size = 0
    photo.preview_sha256 = ''
    photo.original_sha256 = ''
    photo.remote_batch_id = undefined
    const batch = localBatch(photo)
    batch.remote_batch_id = undefined
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    const unlink = installPlatform(storage, true)
    mocks.createBatch.mockResolvedValue({ ok: true, batch_id: 'preview-batch' })
    mocks.uploadPhoto.mockResolvedValue({ ok: true, photo: { status: 'server_saved' } })
    mocks.commitBatch.mockResolvedValue({ ok: true })

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.retry('preview-recovery')
    await vi.waitFor(() => expect(queueRuntime.state.photos[0]?.status).toBe('desktop_pending'))
    expect(mocks.uploadPhoto).toHaveBeenCalledWith('preview-batch', '/user/32-transfer.jpg', expect.any(Object), expect.any(Function))
    expect(mocks.persistPreparedPreview).toHaveBeenCalled()
    expect(mocks.downloadServerPreview).not.toHaveBeenCalled()
    expect(unlink).toHaveBeenCalledWith('/user/32-original.jpg')
    expect(queueRuntime.state.photos[0]).toMatchObject({
      original_path: '',
      preview_path: '/user/preview.jpg',
      preview_size: 90_000,
      preview_recovery_pending: false,
    })
  })

  it('旧队列只有原图时自动迁移为 1MB JPEG 归档图，且不伪造相册来源', async () => {
    const photo = localPhoto('32', 'legacy-original-only')
    photo.status = 'uploading'
    photo.remote_batch_id = undefined
    photo.draft = { ...draft, capture_source: undefined, transfer_profile: undefined }
    delete photo.transfer_path
    delete photo.transfer_size
    delete photo.transfer_sha256
    delete photo.transfer_filename
    delete photo.transfer_width
    delete photo.transfer_height
    const batch = localBatch(photo)
    batch.remote_batch_id = undefined
    batch.committed = false
    batch.draft = photo.draft
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    const unlink = installPlatform(storage, false)

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('manual')

    expect(queueRuntime.state.photos[0]).toMatchObject({
      status: 'local_ready',
      original_path: '',
      transfer_path: '/user/transfer.jpg',
      transfer_size: 900_000,
      preparation_pending: false,
    })
    expect(queueRuntime.state.photos[0].draft).toMatchObject({ transfer_profile: 'jpeg_1m' })
    expect(queueRuntime.state.photos[0].draft.capture_source).toBeUndefined()
    expect(queueRuntime.state.batches[0].draft.capture_source).toBeUndefined()
    expect(unlink).toHaveBeenCalledWith('/user/32-original.jpg')
    expect(mocks.createBatch).not.toHaveBeenCalled()
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

  it('电脑已归档时释放暂存原图和 1MiB 归档图，100KB 本机预览继续保留', async () => {
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
    expect(unlink).toHaveBeenCalledWith('/user/32-transfer.jpg')
    expect(unlink).not.toHaveBeenCalledWith('/user/32-preview.jpg')
    expect(queueRuntime.state.photos[0]).toMatchObject({ status: 'desktop_imported', original_path: '', original_removed: true, transfer_path: '', preview_path: '/user/32-preview.jpg' })
    expect(queueRuntime.queueBytes.value).toBe(90_000)
    await queueRuntime.resume('manual')
    expect(mocks.batch).toHaveBeenCalledTimes(1)
  })

  it('批次 ACK 返回删除 tombstone 时收敛本地队列，不下载预览也不再轮询', async () => {
    const photo = localPhoto('32', 'deleted-ack-photo')
    photo.status = 'desktop_pending'
    photo.preview_path = ''
    photo.preview_size = 0
    photo.preview_sha256 = ''
    photo.preview_recovery_pending = true
    const batch = localBatch(photo)
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    const unlink = installPlatform(storage, true)
    mocks.batch.mockResolvedValue({
      ok: true,
      batch_id: '18',
      status: 'desktop_imported',
      photos: [{
        photo_uuid: photo.photo_uuid,
        status: 'desktop_imported',
        deleted_at: '2026-08-28T12:30:00Z',
        match_candidates: [],
      }],
    })

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')

    expect(queueRuntime.state.photos[0]).toMatchObject({
      status: 'desktop_imported',
      deleted_at: '2026-08-28T12:30:00Z',
      original_path: '',
      original_removed: true,
      preview_recovery_pending: false,
    })
    expect(queueRuntime.pendingCount.value).toBe(0)
    expect(unlink).toHaveBeenCalledWith('/user/32-original.jpg')
    expect(mocks.photo).not.toHaveBeenCalled()
    expect(mocks.downloadServerPreview).not.toHaveBeenCalled()

    await queueRuntime.resume('manual')
    expect(mocks.batch).toHaveBeenCalledTimes(1)
    expect(mocks.photo).not.toHaveBeenCalled()
  })

  it('上传只发送 JPEG 传输图，server_saved 后立即释放传输图但保留预览', async () => {
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
    expect(mocks.uploadPhoto).toHaveBeenCalledWith('19', '/user/32-transfer.jpg', expect.objectContaining({
      sha256: 'd'.repeat(64),
      original_size_bytes: 900_000,
      original_filename: '32.jpg',
      original_mime_type: 'image/jpeg',
      transfer_profile: 'jpeg_1m',
    }), expect.any(Function))
    const metadata = mocks.uploadPhoto.mock.calls[0][2]
    expect(metadata).not.toHaveProperty('preview_sha256')
    expect(unlink).toHaveBeenCalledWith('/user/32-transfer.jpg')
    expect(unlink).not.toHaveBeenCalledWith('/user/32-preview.jpg')
    expect(queueRuntime.state.photos[0]).toMatchObject({ status: 'desktop_pending', transfer_path: '', preview_path: '/user/32-preview.jpg' })
  })

  it('传输图超过 1MiB 时不调用任何上传接口', async () => {
    const photo = localPhoto('32', 'photo-large')
    photo.status = 'local_ready'
    photo.transfer_size = 1024 * 1024 + 1
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

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    expect(mocks.createBatch).not.toHaveBeenCalled()
    expect(mocks.uploadPhoto).not.toHaveBeenCalled()
    expect(mocks.uploadPhotoInChunks).not.toHaveBeenCalled()
    expect(queueRuntime.state.photos[0]).toMatchObject({
      status: 'failed',
      retryable: false,
      failure_code: 'TRANSFER_FILE_INVALID',
      transfer_path: '/user/32-transfer.jpg',
    })
    expect(queueRuntime.state.photos[0].error).toContain('超过限制')
  })

  it('可重试的上传网络错误回到待上传，并按退避时间自动续传', async () => {
    const photo = localPhoto('32', 'photo-network-retry')
    photo.status = 'local_ready'
    photo.progress = 0
    const batch = localBatch(photo)
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    installPlatform(storage, true)
    const { ApiError } = await import('@/api/client')
    mocks.uploadPhoto
      .mockRejectedValueOnce(new ApiError('上传超时', 'UPLOAD_INTERRUPTED', true))
      .mockRejectedValueOnce(new ApiError('网关超时', 'HTTP_504', false, 504))
      .mockResolvedValueOnce({ ok: true, photo: { status: 'server_saved' } })
    mocks.commitBatch.mockResolvedValue({ ok: true })

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    expect(queueRuntime.state.photos[0]).toMatchObject({
      status: 'local_ready',
      auto_retry_pending: true,
      auto_retry_attempts: 1,
      retryable: true,
    })
    expect(queueRuntime.state.photos[0].error).toContain('网络不稳定，将自动重试')
    expect(Date.parse(queueRuntime.state.photos[0].next_retry_at || '')).toBeGreaterThan(Date.now())

    await queueRuntime.resume('manual')
    expect(mocks.uploadPhoto).toHaveBeenCalledTimes(1)

    queueRuntime.state.photos[0].next_retry_at = '2000-01-01T00:00:00.000Z'
    await queueRuntime.resume('manual')
    expect(mocks.uploadPhoto).toHaveBeenCalledTimes(2)
    expect(queueRuntime.state.photos[0]).toMatchObject({ status: 'local_ready', auto_retry_pending: true, auto_retry_attempts: 2 })
    expect(Date.parse(queueRuntime.state.photos[0].next_retry_at || '')).toBeGreaterThanOrEqual(Date.now() + 59_000)

    await queueRuntime.resume('manual')
    expect(mocks.uploadPhoto).toHaveBeenCalledTimes(2)

    queueRuntime.state.photos[0].next_retry_at = '2000-01-01T00:00:00.000Z'
    await queueRuntime.resume('manual')
    expect(mocks.uploadPhoto).toHaveBeenCalledTimes(3)
    expect(mocks.uploadPhoto.mock.calls.map((call) => call[2].photo_uuid)).toEqual(['photo-network-retry', 'photo-network-retry', 'photo-network-retry'])
    expect(queueRuntime.state.photos[0]).toMatchObject({ status: 'desktop_pending', auto_retry_pending: undefined, next_retry_at: undefined })
  })

  it('原图已上服务器后遇到普通网络中断，保持 server_saved 并延时重试归档提交', async () => {
    const photo = localPhoto('32', 'photo-commit-retry')
    photo.status = 'server_saved'
    photo.original_path = ''
    photo.original_removed = true
    const batch = localBatch(photo)
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    installPlatform(storage, true)
    mocks.commitBatch
      .mockRejectedValueOnce({ errMsg: 'request:fail socket closed' })
      .mockResolvedValueOnce({ ok: true })

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    expect(queueRuntime.state.photos[0]).toMatchObject({
      status: 'server_saved',
      retry_from: 'server_saved',
      auto_retry_pending: true,
    })
    expect(queueRuntime.state.photos[0].error).toContain('网络不稳定，将自动重试')

    await queueRuntime.resume('manual')
    expect(mocks.commitBatch).toHaveBeenCalledTimes(1)

    queueRuntime.state.photos[0].next_retry_at = '2000-01-01T00:00:00.000Z'
    await queueRuntime.resume('manual')
    expect(mocks.commitBatch).toHaveBeenCalledTimes(2)
    expect(queueRuntime.state.photos[0].status).toBe('desktop_pending')
  })

  it('混合批次可在旧工程补齐信息；远端批次先 PATCH 再继续上传', async () => {
    const saved = localPhoto('32', 'already-server-saved')
    saved.status = 'server_saved'
    saved.original_path = ''
    saved.transfer_path = ''
    saved.draft = { ...draft, project_id: '32:OLD', project_name: undefined, assignment: undefined }
    const repair = localPhoto('32', 'archive-info-required')
    repair.status = 'failed'
    repair.failure_code = 'ARCHIVE_INFO_REQUIRED'
    repair.retry_from = 'local_ready'
    repair.retryable = false
    repair.draft = { ...saved.draft }
    const batch = localBatch(repair)
    batch.photo_uuids = [saved.photo_uuid, repair.photo_uuid]
    batch.draft = { ...saved.draft }
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [saved, repair], batches: [batch] },
    ]])
    installPlatform(storage, false)
    mocks.batch.mockResolvedValue({
      ok: true,
      batch_id: '18',
      status: 'server_saved',
      photos: [{ photo_uuid: saved.photo_uuid, status: 'server_saved' }],
    })
    mocks.updateBatchArchiveInfo.mockResolvedValue({ ok: true })
    mocks.uploadPhoto.mockResolvedValue({ ok: true, photo: { status: 'server_saved' } })
    mocks.commitBatch.mockResolvedValue({ ok: true })
    const completedAssignment = { ...draft.assignment! }

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    queueRuntime.completeArchiveInfo(batch.client_batch_id, '旧工程精确名称', completedAssignment)
    await vi.waitFor(() => expect(queueRuntime.state.running).toBe(false))

    expect(queueRuntime.state.batches[0]).toMatchObject({
      archive_info_sync_pending: true,
      draft: { project_id: '32:OLD', project_name: '旧工程精确名称', assignment: completedAssignment },
    })
    expect(queueRuntime.state.photos.find((photo) => photo.photo_uuid === saved.photo_uuid)?.status).toBe('server_saved')
    expect(queueRuntime.state.photos.find((photo) => photo.photo_uuid === repair.photo_uuid)?.status).toBe('local_ready')
    expect(mocks.updateBatchArchiveInfo).not.toHaveBeenCalled()
    expect(mocks.uploadPhoto).not.toHaveBeenCalled()

    ;(globalThis as any).uni.getNetworkType = ({ success }: any) => success({ networkType: 'wifi' })
    await queueRuntime.resume('network-restored')

    expect(mocks.updateBatchArchiveInfo).toHaveBeenCalledWith('18', completedAssignment)
    expect(mocks.uploadPhoto).toHaveBeenCalledWith('18', '/user/32-transfer.jpg', expect.objectContaining({ photo_uuid: repair.photo_uuid }), expect.any(Function))
    expect(mocks.updateBatchArchiveInfo.mock.invocationCallOrder[0]).toBeLessThan(mocks.uploadPhoto.mock.invocationCallOrder[0])
    expect(queueRuntime.state.batches[0]).toMatchObject({ committed: true })
    expect(queueRuntime.state.batches[0].archive_info_sync_pending).toBeUndefined()
    expect(queueRuntime.state.photos.map((photo) => photo.status)).toEqual(['desktop_pending', 'desktop_pending'])
  })

  it('已上传批次补归档信息遇永久403后停止 PATCH 循环并保留100KB本机预览', async () => {
    const saved = localPhoto('32', 'archive-sync-revoked')
    saved.status = 'server_saved'
    saved.original_path = ''
    saved.original_removed = true
    saved.transfer_path = ''
    saved.transfer_size = 0
    saved.transfer_sha256 = ''
    saved.transfer_filename = ''
    saved.preview_path = '/user/32-preview.jpg'
    saved.preview_size = 90_000
    const batch = localBatch(saved)
    batch.archive_info_sync_pending = true
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [saved], batches: [batch] },
    ]])
    const unlink = installPlatform(storage, true)
    mocks.batch.mockResolvedValue({
      ok: true,
      batch_id: '18',
      status: 'server_saved',
      photos: [{ photo_uuid: saved.photo_uuid, status: 'server_saved' }],
    })
    const { ApiError } = await import('@/api/client')
    mocks.updateBatchArchiveInfo.mockRejectedValue(new ApiError('已无工程采集权限', 'project_access_revoked', false, 403))

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('network-restored')

    expect(mocks.updateBatchArchiveInfo).toHaveBeenCalledTimes(1)
    expect(queueRuntime.state.batches[0]).toMatchObject({
      archive_info_sync_error: '已无此工程采集权限；已停止自动同步，服务器照片和本机预览均已保留',
      archive_info_sync_failure_code: 'project_access_revoked',
      archive_info_sync_retryable: false,
    })
    expect(queueRuntime.state.batches[0].archive_info_sync_pending).toBeUndefined()
    expect(queueRuntime.state.photos[0]).toMatchObject({
      status: 'failed',
      retry_from: 'server_saved',
      retryable: false,
      failure_code: 'project_access_revoked',
      preview_path: '/user/32-preview.jpg',
      preview_size: 90_000,
      error: '已无此工程采集权限；服务器照片和本机100KB预览均已保留',
    })
    expect(unlink).not.toHaveBeenCalledWith('/user/32-preview.jpg')

    await queueRuntime.resume('manual')
    await queueRuntime.resume('network-restored')
    expect(mocks.updateBatchArchiveInfo).toHaveBeenCalledTimes(1)
    expect(mocks.commitBatch).not.toHaveBeenCalled()
    expect(queueRuntime.state.photos[0]).toMatchObject({ status: 'failed', retryable: false })

    mocks.updateBatchArchiveInfo.mockResolvedValueOnce({ ok: true })
    mocks.commitBatch.mockResolvedValueOnce({ ok: true })
    await queueRuntime.retry(saved.photo_uuid)
    expect(mocks.updateBatchArchiveInfo).toHaveBeenCalledTimes(2)
    expect(mocks.commitBatch).toHaveBeenCalledTimes(1)
    expect(queueRuntime.state.batches[0].archive_info_sync_failure_code).toBeUndefined()
    expect(queueRuntime.state.photos[0].status).toBe('desktop_pending')
  })

  it('服务器预览恢复失败后按退避时间重试，同一轮询不重复请求', async () => {
    const photo = localPhoto('32', 'photo-preview-retry')
    photo.status = 'server_saved'
    photo.original_path = ''
    photo.original_removed = true
    photo.preview_path = ''
    photo.preview_size = 0
    photo.preview_sha256 = ''
    const batch = localBatch(photo)
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    installPlatform(storage, true)
    mocks.batch.mockResolvedValue({
      ok: true,
      batch_id: '18',
      status: 'server_saved',
      photos: [{ photo_uuid: photo.photo_uuid, status: 'server_saved' }],
    })
    const { ApiError } = await import('@/api/client')
    mocks.photo
      .mockRejectedValueOnce(new ApiError('预览服务暂时不可用', 'HTTP_503', false, 503))
      .mockResolvedValueOnce({ ok: true, photo: { download_url: 'https://api.example.test/preview' } })

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    expect(mocks.photo).toHaveBeenCalledTimes(1)
    expect(queueRuntime.state.photos[0]).toMatchObject({
      preview_path: '',
      preview_recovery_pending: true,
      preview_retry_attempts: 1,
    })
    expect(Date.parse(queueRuntime.state.photos[0].preview_next_retry_at || '')).toBeGreaterThan(Date.now())

    await queueRuntime.resume('manual')
    expect(mocks.photo).toHaveBeenCalledTimes(1)

    queueRuntime.state.photos[0].preview_next_retry_at = '2000-01-01T00:00:00.000Z'
    await queueRuntime.resume('manual')
    expect(mocks.photo).toHaveBeenCalledTimes(2)
    expect(queueRuntime.state.photos[0]).toMatchObject({
      preview_path: '/user/server-preview.jpg',
      preview_recovery_pending: false,
      preview_retry_attempts: undefined,
      preview_next_retry_at: undefined,
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

  it('恰好 1MiB 的 JPEG 归档图可直传，超过边界才拒绝', async () => {
    const photo = localPhoto('32', 'one-mib-photo')
    photo.status = 'local_ready'
    photo.transfer_size = 1024 * 1024
    photo.remote_batch_id = undefined
    const batch = localBatch(photo)
    batch.remote_batch_id = undefined
    batch.committed = false
    const storage = new Map<string, any>([[
      'engineering-image:queue:v2:account:32',
      { owner_account_id: '32', photos: [photo], batches: [batch] },
    ]])
    installPlatform(storage, true)
    mocks.createBatch.mockResolvedValue({ ok: true, batch_id: 'one-mib-batch' })
    mocks.uploadPhoto.mockResolvedValue({ ok: true, photo: { status: 'server_saved' } })
    mocks.commitBatch.mockResolvedValue({ ok: true })

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')
    expect(mocks.uploadPhoto).toHaveBeenCalledWith('one-mib-batch', '/user/32-transfer.jpg', expect.objectContaining({
      photo_uuid: 'one-mib-photo',
      original_size_bytes: 1024 * 1024,
      transfer_profile: 'jpeg_1m',
    }), expect.any(Function))
    expect(mocks.uploadPhotoInChunks).not.toHaveBeenCalled()
    expect(queueRuntime.state.photos[0].status).toBe('desktop_pending')
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

  it('成员被移除后停止自动重试且保留本机 1MiB 归档图', async () => {
    const photo = localPhoto('32', 'revoked-photo')
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
    const { ApiError } = await import('@/api/client')
    mocks.createBatch.mockRejectedValue(new ApiError('已无工程访问权限', 'project_access_revoked', false, 403))

    const { queueRuntime } = await import('@/services/queue-runtime')
    queueRuntime.setOwner('32')
    await queueRuntime.resume('app-show')

    expect(queueRuntime.state.photos[0]).toMatchObject({
      status: 'failed',
      retryable: false,
      transfer_path: '/user/32-transfer.jpg',
      error: '已无此工程采集权限；1MB 归档图仍保存在本机',
    })
    expect(unlink).not.toHaveBeenCalled()
  })
})
