import { computed, reactive } from 'vue'
import { ApiError } from '@/api/client'
import { mobileApi } from '@/api/mobile'
import type { CreateBatchPayload } from '@/api/contracts'
import type { Assignment, LocalBatch, LocalPhoto, PhotoStatus, UploadDraft } from '@/types/domain'
import { createUuid } from './ids'
import { hashFile } from './sha256'
import { downloadServerPreview, getSourceFileSize, inspectOriginalSource, persistPreparedPreview, preparePreview } from './image-compression'
import { MAX_ORIGINAL_BYTES, MAX_PREVIEW_BYTES, MAX_QUEUE_BYTES, MAX_UPLOAD_CONCURRENCY, requiresChunkedUpload, retainedQueueBytes } from './queue-policy'
import { canTransition, recoverInterruptedStatus } from './photo-state'
import { notifyAuthExpired } from './auth-expiry-coordinator'
import { queueFileStore } from './queue-storage'
import { UploadPausedError, uploadPhotoInChunks } from './chunk-upload'

interface QueueState {
  ownerAccountId: string
  hydrated: boolean
  online: boolean
  running: boolean
  preparing: boolean
  foreground: boolean
  prepareProgress: { current: number; total: number; message: string }
  photos: LocalPhoto[]
  batches: LocalBatch[]
}

const state = reactive<QueueState>({
  ownerAccountId: '',
  hydrated: false,
  online: true,
  running: false,
  preparing: false,
  foreground: true,
  prepareProgress: { current: 0, total: 0, message: '' },
  photos: [],
  batches: [],
})

let networkListenerRegistered = false
let ownerGeneration = 0
let foregroundTimer: ReturnType<typeof setInterval> | null = null
const AUTO_RETRY_DELAYS_MS = [30_000, 60_000, 120_000, 300_000] as const

function now(): string {
  return new Date().toISOString()
}

function isCurrentOwner(owner: string, generation?: number): boolean {
  return Boolean(owner && owner === state.ownerAccountId && (generation === undefined || generation === ownerGeneration))
}

function persist(owner = state.ownerAccountId): void {
  if (!isCurrentOwner(owner)) return
  queueFileStore.persistSnapshot(owner, JSON.parse(JSON.stringify(state.photos)), JSON.parse(JSON.stringify(state.batches)))
  try {
    uni.setStorageSync(`engineering-image:queue-count:v3:${owner}`, state.photos.filter((photo) => photo.status !== 'desktop_imported').length)
    uni.setStorageSync('engineering-image:active-queue-owner:v3', owner)
  } catch { /* 徽标是可丢缓存；文件分片才是队列权威数据。 */ }
}

function isManagedSavedPath(path: string): boolean {
  const wxApi = (globalThis as { wx?: any }).wx
  const root = String(wxApi?.env?.USER_DATA_PATH || '')
  return Boolean(path && root && (path === root || path.startsWith(`${root}/`)))
}

async function removeSavedFile(path: string): Promise<boolean> {
  if (!path) return true
  if (!isManagedSavedPath(path)) return false
  const wxApi = (globalThis as { wx?: any }).wx
  if (!wxApi?.getFileSystemManager) return false
  return new Promise((resolve) => {
    wxApi.getFileSystemManager().unlink({
      filePath: path,
      success: () => resolve(true),
      fail: (error: { errMsg?: string }) => resolve(String(error?.errMsg || '').includes('no such file')),
    })
  })
}

function setStatus(photo: LocalPhoto, next: PhotoStatus, force = false): void {
  if (!isCurrentOwner(photo.owner_account_id)) return
  if (!force && !canTransition(photo.status, next)) throw new Error(`非法照片状态变化：${photo.status} -> ${next}`)
  photo.status = next
  photo.updated_at = now()
  if (next !== 'failed') {
    photo.error = undefined
    photo.retryable = undefined
    photo.retry_from = undefined
    photo.failure_code = undefined
    photo.auto_retry_pending = undefined
    photo.next_retry_at = undefined
    if (!['local_ready', 'uploading'].includes(next)) photo.auto_retry_attempts = undefined
  }
  persist(photo.owner_account_id)
}

function isAuthExpired(error: unknown): error is ApiError {
  return error instanceof ApiError && (error.statusCode === 401 || ['unauthorized', 'token_expired', 'AUTH_EXPIRED'].includes(error.code))
}

function isProjectAccessRevoked(error: unknown): error is ApiError {
  if (!(error instanceof ApiError)) return false
  return ['project_access_revoked', 'project_permission_denied', 'project_access_denied', 'project_not_found'].includes(String(error.code || '').toLowerCase())
}

function errorMessage(error: unknown, fallback = '处理失败'): string {
  if (error instanceof Error && error.message) return error.message
  if (error && typeof error === 'object' && 'errMsg' in error) return String((error as { errMsg?: unknown }).errMsg || fallback)
  return fallback
}

function isTransientNetworkError(error: unknown): boolean {
  if (isAuthExpired(error)) return false
  if (error instanceof ApiError) {
    const status = Number(error.statusCode || 0)
    return error.retryable
      || [408, 425, 429].includes(status)
      || (status >= 500 && status <= 599)
      || ['NETWORK_ERROR', 'UPLOAD_INTERRUPTED', 'REQUEST_TIMEOUT', 'TIMEOUT'].includes(error.code)
  }
  const message = errorMessage(error, '')
  return /(network|timeout|timed out|request:fail|uploadfile:fail|connection|socket|网络|超时|断网|连接|中断)/i.test(message)
}

function automaticRetryTarget(retryFrom: PhotoStatus): PhotoStatus {
  if (['local_ready', 'uploading'].includes(retryFrom)) return 'local_ready'
  if (retryFrom === 'analyzing') return 'server_saved'
  return retryFrom
}

function isAutomaticRetryDue(photo: LocalPhoto): boolean {
  if (!photo.auto_retry_pending || !photo.next_retry_at) return true
  const retryAt = Date.parse(photo.next_retry_at)
  return !Number.isFinite(retryAt) || retryAt <= Date.now()
}

function isPreviewRecoveryDue(photo: LocalPhoto): boolean {
  if (!photo.preview_next_retry_at) return true
  const retryAt = Date.parse(photo.preview_next_retry_at)
  return !Number.isFinite(retryAt) || retryAt <= Date.now()
}

function beginAutomaticRetryAttempt(photo: LocalPhoto): void {
  if (!photo.auto_retry_pending) return
  photo.auto_retry_pending = undefined
  photo.next_retry_at = undefined
  photo.error = undefined
  photo.retryable = undefined
  photo.retry_from = undefined
  photo.failure_code = undefined
  photo.updated_at = now()
}

function scheduleAutomaticRetry(photo: LocalPhoto, error: unknown, retryFrom: PhotoStatus): boolean {
  if (!isCurrentOwner(photo.owner_account_id) || !isTransientNetworkError(error)) return false
  const attempts = Math.max(0, Number(photo.auto_retry_attempts || 0)) + 1
  const delay = AUTO_RETRY_DELAYS_MS[Math.min(attempts - 1, AUTO_RETRY_DELAYS_MS.length - 1)]
  const waitText = delay < 60_000 ? `${Math.ceil(delay / 1_000)} 秒` : `${Math.ceil(delay / 60_000)} 分钟`
  const target = automaticRetryTarget(retryFrom)
  photo.status = target
  photo.progress = target === 'local_ready' ? 0 : 100
  photo.retry_from = retryFrom
  photo.retryable = true
  photo.failure_code = error instanceof ApiError ? error.code : 'NETWORK_ERROR'
  photo.error = `网络不稳定，将自动重试（约 ${waitText} 后）`
  photo.auto_retry_pending = true
  photo.auto_retry_attempts = attempts
  photo.next_retry_at = new Date(Date.now() + delay).toISOString()
  photo.updated_at = now()
  persist(photo.owner_account_id)
  return true
}

function markFailed(photo: LocalPhoto, error: unknown, retryFrom: PhotoStatus, preparation = false): void {
  if (!isCurrentOwner(photo.owner_account_id)) return
  photo.retry_from = retryFrom
  photo.status = 'failed'
  const message = isProjectAccessRevoked(error) ? '已无此工程采集权限；原图仍保存在本机' : errorMessage(error)
  photo.error = preparation ? `原图已安全保存；${message}` : message
  photo.failure_code = isAuthExpired(error) ? 'AUTH_EXPIRED' : error instanceof ApiError ? error.code : undefined
  photo.retryable = isProjectAccessRevoked(error) ? false : isAuthExpired(error) ? true : error instanceof ApiError ? error.retryable : true
  photo.auto_retry_pending = undefined
  photo.auto_retry_attempts = undefined
  photo.next_retry_at = undefined
  photo.preparation_pending = preparation
  photo.updated_at = now()
  persist(photo.owner_account_id)
}

async function cleanupOriginal(photo: LocalPhoto): Promise<void> {
  if (!isCurrentOwner(photo.owner_account_id) || !photo.original_path) return
  const removed = await removeSavedFile(photo.original_path)
  if (!isCurrentOwner(photo.owner_account_id) || !removed) return
  photo.original_path = ''
  photo.original_removed = true
  persist(photo.owner_account_id)
  queueFileStore.clearOriginalWal(photo.owner_account_id, photo.photo_uuid)
}

async function markDesktopImported(photo: LocalPhoto): Promise<void> {
  if (!isCurrentOwner(photo.owner_account_id)) return
  if (photo.status !== 'desktop_imported') setStatus(photo, 'desktop_imported', !canTransition(photo.status, 'desktop_imported'))
  await cleanupOriginal(photo)
}

function getNetworkType(): Promise<boolean> {
  return new Promise((resolve) => {
    uni.getNetworkType({ success: ({ networkType }) => resolve(networkType !== 'none'), fail: () => resolve(true) })
  })
}

async function runWithConcurrency<T>(items: T[], limit: number, worker: (item: T) => Promise<void>): Promise<void> {
  let cursor = 0
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const item = items[cursor]
      cursor += 1
      await worker(item)
    }
  })
  await Promise.all(workers)
}

function defaultTitle(draft: UploadDraft): string {
  if (draft.requirement?.photo_requirement_name) return draft.requirement.photo_requirement_name
  if (draft.scope === 'other') return draft.assignment?.other_node_name || '其它现场影像'
  return draft.assignment?.process_name || draft.assignment?.unit_name || '现场工程影像'
}

function recoveryPhoto(owner: string, batch: LocalBatch, original: { originalPath: string; originalSize: number; originalFilename: string }, photoUuid = createUuid()): LocalPhoto {
  const createdAt = now()
  return {
    owner_account_id: owner,
    photo_uuid: photoUuid,
    client_batch_id: batch.client_batch_id,
    original_path: original.originalPath,
    original_size: original.originalSize,
    original_sha256: '',
    original_filename: original.originalFilename,
    original_mime_type: '',
    preview_path: '',
    preview_size: 0,
    preview_sha256: '',
    preview_width: 0,
    preview_height: 0,
    width: 0,
    height: 0,
    orientation: 1,
    client_captured_at: createdAt,
    title: defaultTitle(batch.draft),
    photo_date: createdAt.slice(0, 10),
    draft: JSON.parse(JSON.stringify(batch.draft)),
    status: 'failed',
    retry_from: 'local_ready',
    progress: 0,
    error: '原图已安全保存，正在生成本机预览',
    retryable: true,
    preparation_pending: true,
    created_at: createdAt,
    updated_at: createdAt,
  }
}

async function completePreparation(photo: LocalPhoto, generation = ownerGeneration): Promise<boolean> {
  const owner = photo.owner_account_id
  if (!isCurrentOwner(owner, generation) || !photo.original_path) return false
  try {
    if (!photo.original_mime_type || !photo.width || !photo.height) {
      const inspected = await inspectOriginalSource(photo.original_path, photo.original_filename, photo.client_captured_at)
      if (!isCurrentOwner(owner, generation)) return false
      photo.width = inspected.width
      photo.height = inspected.height
      photo.orientation = inspected.orientation
      photo.client_captured_at = inspected.capturedAt
      photo.photo_date = inspected.capturedAt.slice(0, 10)
      photo.original_mime_type = inspected.originalMimeType
      persist(owner)
    }
    if (!photo.preview_path) {
      try {
        const prepared = await preparePreview(photo.original_path, photo.original_filename, photo.client_captured_at)
        if (!isCurrentOwner(owner, generation)) return false
        const saved = await persistPreparedPreview(prepared)
        if (!isCurrentOwner(owner, generation)) {
          await removeSavedFile(saved.previewPath)
          return false
        }
        photo.preview_path = saved.previewPath
        photo.preview_size = saved.previewSize
        photo.preview_width = saved.previewWidth
        photo.preview_height = saved.previewHeight
        photo.preview_recovery_pending = false
        photo.preview_error = undefined
        persist(owner)
      } catch (error) {
        // 本机压缩能力不应阻断原图中转；服务器会从原图生成严格不超过 100KB 的 JPEG。
        photo.preview_recovery_pending = true
        photo.preview_error = errorMessage(error, '本机预览生成失败，将从服务器恢复')
        persist(owner)
      }
    }
    if (!photo.original_sha256) {
      photo.original_sha256 = await hashFile(photo.original_path)
      if (!isCurrentOwner(owner, generation)) return false
      persist(owner)
    }
    if (photo.preview_path && !photo.preview_sha256) {
      photo.preview_sha256 = await hashFile(photo.preview_path)
      if (!isCurrentOwner(owner, generation)) return false
      persist(owner)
    }
    photo.preparation_pending = false
    setStatus(photo, 'local_ready', true)
    return true
  } catch (error) {
    markFailed(photo, error, 'local_ready', true)
    return false
  }
}

async function repairIncompletePhotos(generation: number): Promise<void> {
  const items = state.photos.filter((photo) => photo.preparation_pending && photo.original_path)
  for (const photo of items) {
    if (!isCurrentOwner(photo.owner_account_id, generation)) return
    await completePreparation(photo, generation)
  }
}

async function recoverServerPreview(photo: LocalPhoto, generation: number): Promise<void> {
  const owner = photo.owner_account_id
  if (!isCurrentOwner(owner, generation) || photo.preview_path) return
  let savedPath = ''
  try {
    const detail = await mobileApi.photo(photo.photo_uuid)
    const url = detail.photo.download_url || detail.photo.image_url || ''
    const saved = await downloadServerPreview(url)
    savedPath = saved.previewPath
    const sha256 = await hashFile(saved.previewPath)
    if (!isCurrentOwner(owner, generation)) {
      await removeSavedFile(saved.previewPath)
      return
    }
    photo.preview_path = saved.previewPath
    photo.preview_size = saved.previewSize
    photo.preview_sha256 = sha256
    photo.preview_width ||= photo.width
    photo.preview_height ||= photo.height
    photo.preview_recovery_pending = false
    photo.preview_error = undefined
    photo.preview_retry_attempts = undefined
    photo.preview_next_retry_at = undefined
    persist(owner)
  } catch (error) {
    if (savedPath) await removeSavedFile(savedPath)
    throw error
  }
}

async function tryRecoverServerPreview(photo: LocalPhoto, generation: number): Promise<void> {
  if (photo.deleted_at || photo.preview_path || !isCurrentOwner(photo.owner_account_id, generation) || !isPreviewRecoveryDue(photo)) return
  try {
    await recoverServerPreview(photo, generation)
  } catch (error) {
    if (!isCurrentOwner(photo.owner_account_id, generation)) return
    const attempts = Math.max(0, Number(photo.preview_retry_attempts || 0)) + 1
    const delay = AUTO_RETRY_DELAYS_MS[Math.min(attempts - 1, AUTO_RETRY_DELAYS_MS.length - 1)]
    photo.preview_recovery_pending = true
    photo.preview_error = errorMessage(error, '服务器预览稍后自动恢复')
    photo.preview_retry_attempts = attempts
    photo.preview_next_retry_at = new Date(Date.now() + delay).toISOString()
    persist(photo.owner_account_id)
  }
}

async function uploadOne(photo: LocalPhoto, batch: LocalBatch, generation: number): Promise<void> {
  const owner = batch.owner_account_id
  if (!isCurrentOwner(owner, generation) || !state.online || photo.status !== 'local_ready' || !isAutomaticRetryDue(photo)) return
  if (!photo.original_path || !photo.original_sha256 || !photo.original_mime_type) {
    markFailed(photo, new Error('本机原图信息不完整，请先恢复照片'), 'local_ready', true)
    return
  }
  try {
    beginAutomaticRetryAttempt(photo)
    setStatus(photo, 'uploading')
    photo.progress = 1
    persist(owner)
    const metadata = {
      photo_uuid: photo.photo_uuid,
      client_captured_at: photo.client_captured_at,
      orientation: photo.orientation,
      width: photo.width,
      height: photo.height,
      sha256: photo.original_sha256,
      original_size_bytes: photo.original_size,
      original_filename: photo.original_filename,
      original_mime_type: photo.original_mime_type,
      title: photo.title,
      photo_date: photo.photo_date,
      capture_source: photo.draft.capture_source,
    }
    if (!requiresChunkedUpload(photo.original_size)) {
      photo.upload_mode = 'direct'
      persist(owner)
      await mobileApi.uploadPhoto(batch.remote_batch_id!, photo.original_path, metadata, (progress) => {
        if (isCurrentOwner(owner, generation)) photo.progress = progress
      })
    } else {
      photo.upload_mode = 'chunked'
      persist(owner)
      await uploadPhotoInChunks({
        batchId: batch.remote_batch_id!,
        filePath: photo.original_path,
        metadata,
        previousUploadedChunks: photo.uploaded_chunks,
        shouldContinue: () => isCurrentOwner(owner, generation) && state.online && state.foreground,
        onCheckpoint: (checkpoint) => {
          if (!isCurrentOwner(owner, generation)) return
          photo.chunk_upload_id = checkpoint.uploadId
          photo.upload_chunk_size = checkpoint.chunkSize
          photo.upload_total_chunks = checkpoint.totalChunks
          photo.uploaded_chunks = checkpoint.uploadedChunks
          persist(owner)
        },
        onProgress: (progress) => {
          if (isCurrentOwner(owner, generation)) photo.progress = progress
        },
      })
    }
    if (!isCurrentOwner(owner, generation)) return
    photo.progress = 100
    photo.server_saved_at = now()
    setStatus(photo, 'server_saved')
    await tryRecoverServerPreview(photo, generation)
    await cleanupOriginal(photo)
  } catch (error) {
    if (!isCurrentOwner(owner, generation)) return
    if (!state.online || error instanceof UploadPausedError) {
      setStatus(photo, 'local_ready')
      return
    }
    if (!scheduleAutomaticRetry(photo, error, 'uploading')) markFailed(photo, error, 'uploading')
    if (isAuthExpired(error)) void notifyAuthExpired(owner)
  }
}

const REMOTE_STATUS_RANK: Partial<Record<PhotoStatus, number>> = {
  server_saved: 1,
  analyzing: 2,
  needs_review: 3,
  desktop_pending: 4,
  desktop_imported: 5,
}

async function applyRemoteStatus(photo: LocalPhoto, remoteStatus: string): Promise<void> {
  if (!(remoteStatus in REMOTE_STATUS_RANK)) return
  const target = remoteStatus as PhotoStatus
  const currentRank = REMOTE_STATUS_RANK[photo.status] || 0
  const targetRank = REMOTE_STATUS_RANK[target] || 0
  const failedDuringUpload = photo.status === 'failed' && ['local_ready', 'uploading'].includes(photo.retry_from || 'local_ready') && !photo.preparation_pending
  if (targetRank > currentRank || failedDuringUpload) setStatus(photo, target, !canTransition(photo.status, target))
  if (targetRank >= 1) {
    await tryRecoverServerPreview(photo, ownerGeneration)
    await cleanupOriginal(photo)
  }
}

async function refreshRemoteBatch(batch: LocalBatch, generation: number): Promise<void> {
  const owner = batch.owner_account_id
  if (!batch.remote_batch_id || !isCurrentOwner(owner, generation)) return
  const localPhotos = state.photos.filter((photo) => batch.photo_uuids.includes(photo.photo_uuid))
  if (!localPhotos.length) return
  try {
    const detail = await mobileApi.batch(batch.remote_batch_id)
    if (!isCurrentOwner(owner, generation)) return
    for (const remote of detail.photos) {
      const local = localPhotos.find((photo) => photo.photo_uuid === remote.photo_uuid)
      if (!local) continue
      if (remote.deleted_at) {
        local.deleted_at = remote.deleted_at
        local.preview_recovery_pending = false
        local.preview_error = undefined
        local.preview_retry_attempts = undefined
        local.preview_next_retry_at = undefined
        await markDesktopImported(local)
        continue
      }
      local.match_candidates = remote.match_candidates || local.match_candidates
      if (remote.title) local.title = remote.title
      if (remote.photo_date) local.photo_date = remote.photo_date
      await applyRemoteStatus(local, remote.status)
    }
    if (localPhotos.every((photo) => ['needs_review', 'desktop_pending', 'desktop_imported'].includes(photo.status))) batch.analyzed = batch.draft.mode === 'auto' || batch.analyzed
    if (localPhotos.every((photo) => ['desktop_pending', 'desktop_imported'].includes(photo.status))) batch.committed = true
    persist(owner)
  } catch (error) {
    // 状态刷新是尽力而为；绝不把服务器已保存的照片降级。
    if (isAuthExpired(error)) void notifyAuthExpired(owner)
  }
}

async function processBatch(batch: LocalBatch, generation: number): Promise<void> {
  const owner = batch.owner_account_id
  if (!isCurrentOwner(owner, generation)) return
  const photos = state.photos.filter((photo) => batch.photo_uuids.includes(photo.photo_uuid))
  const uploadable = photos.filter((photo) => photo.status === 'local_ready' && isAutomaticRetryDue(photo))
  if (!batch.remote_batch_id && !uploadable.length) return
  if (!batch.remote_batch_id) {
    const payload: CreateBatchPayload = {
      client_batch_id: batch.client_batch_id,
      project_id: batch.draft.project_id,
      scope: batch.draft.scope,
      category: batch.draft.category,
      mode: batch.draft.mode,
      capture_source: batch.draft.capture_source,
      assignment: batch.draft.mode === 'direct' ? batch.draft.assignment : undefined,
      requirement: batch.draft.requirement,
    }
    try {
      uploadable.forEach(beginAutomaticRetryAttempt)
      persist(owner)
      const created = await mobileApi.createBatch(payload)
      if (!isCurrentOwner(owner, generation)) return
      batch.remote_batch_id = created.batch_id
      photos.forEach((photo) => { photo.remote_batch_id = created.batch_id })
      persist(owner)
    } catch (error) {
      uploadable.forEach((photo) => {
        if (!scheduleAutomaticRetry(photo, error, 'local_ready')) markFailed(photo, error, 'local_ready')
      })
      if (isAuthExpired(error)) void notifyAuthExpired(owner)
      return
    }
  }
  await runWithConcurrency(uploadable, MAX_UPLOAD_CONCURRENCY, (photo) => uploadOne(photo, batch, generation))
  if (!isCurrentOwner(owner, generation)) return
  const refreshed = state.photos.filter((photo) => batch.photo_uuids.includes(photo.photo_uuid))
  if (refreshed.some((photo) => ['local_ready', 'uploading', 'failed'].includes(photo.status))) return

  if (batch.draft.mode === 'auto' && !batch.analyzed && refreshed.some((photo) => ['server_saved', 'analyzing'].includes(photo.status))) {
    if (batch.analysis_requested) return
    const serverSavedPhotos = refreshed.filter((photo) => photo.status === 'server_saved')
    if (serverSavedPhotos.some((photo) => !isAutomaticRetryDue(photo))) return
    try {
      serverSavedPhotos.forEach(beginAutomaticRetryAttempt)
      persist(owner)
      const accepted = await mobileApi.analyzeBatch(batch.remote_batch_id!)
      if (!isCurrentOwner(owner, generation)) return
      batch.analysis_requested = true
      batch.analysis_job_id = accepted.job?.job_id || batch.analysis_job_id
      refreshed.filter((photo) => photo.status === 'server_saved').forEach((photo) => setStatus(photo, 'analyzing'))
      persist(owner)
    } catch (error) {
      refreshed.filter((photo) => photo.status === 'server_saved').forEach((photo) => {
        if (!scheduleAutomaticRetry(photo, error, 'analyzing')) markFailed(photo, error, 'analyzing')
      })
      if (isAuthExpired(error)) void notifyAuthExpired(owner)
    }
    return
  }

  if (batch.draft.mode === 'direct' && !batch.committed && refreshed.some((photo) => photo.status === 'server_saved')) {
    const serverSavedPhotos = refreshed.filter((photo) => photo.status === 'server_saved')
    if (serverSavedPhotos.some((photo) => !isAutomaticRetryDue(photo))) return
    try {
      serverSavedPhotos.forEach(beginAutomaticRetryAttempt)
      persist(owner)
      await mobileApi.commitBatch(batch.remote_batch_id!)
      if (!isCurrentOwner(owner, generation)) return
      refreshed.filter((photo) => photo.status === 'server_saved').forEach((photo) => setStatus(photo, 'desktop_pending'))
      batch.committed = true
      persist(owner)
    } catch (error) {
      refreshed.filter((photo) => photo.status === 'server_saved').forEach((photo) => {
        if (!scheduleAutomaticRetry(photo, error, 'server_saved')) markFailed(photo, error, 'server_saved')
      })
      if (isAuthExpired(error)) void notifyAuthExpired(owner)
    }
  }
}

async function resume(reason: 'app-show' | 'network-restored' | 'manual' = 'manual'): Promise<void> {
  if (!state.hydrated) hydrate()
  const owner = state.ownerAccountId
  const generation = ownerGeneration
  if (!owner) return
  await repairIncompletePhotos(generation)
  state.online = await getNetworkType()
  if (!isCurrentOwner(owner, generation) || !state.online || !state.foreground || state.running) return
  state.running = true
  try {
    for (const batch of [...state.batches]) {
      if (!isCurrentOwner(owner, generation) || !state.online) break
      const batchPhotos = state.photos.filter((photo) => batch.photo_uuids.includes(photo.photo_uuid))
      if (batchPhotos.length && batchPhotos.every((photo) => photo.status === 'desktop_imported')) continue
      try {
        await refreshRemoteBatch(batch, generation)
        await processBatch(batch, generation)
      } catch (error) {
        if (!isCurrentOwner(owner, generation)) break
        state.photos.filter((photo) => (
          batch.photo_uuids.includes(photo.photo_uuid)
          && photo.status === 'local_ready'
          && isAutomaticRetryDue(photo)
        ))
          .forEach((photo) => {
            if (!scheduleAutomaticRetry(photo, error, 'local_ready')) markFailed(photo, error, 'local_ready')
          })
        if (isAuthExpired(error)) {
          void notifyAuthExpired(owner)
          break
        }
      }
    }
    for (const photo of state.photos.filter((item) => REMOTE_STATUS_RANK[item.status])) {
      await tryRecoverServerPreview(photo, generation)
      await cleanupOriginal(photo)
    }
  } finally {
    if (isCurrentOwner(owner, generation)) state.running = false
    void reason
  }
}

function registerNetworkListener(): void {
  if (networkListenerRegistered || typeof uni.onNetworkStatusChange !== 'function') return
  networkListenerRegistered = true
  uni.onNetworkStatusChange(({ isConnected }) => {
    state.online = isConnected
    if (isConnected && state.ownerAccountId && state.foreground) void resume('network-restored')
  })
}

function hydrate(): void {
  if (state.hydrated || !state.ownerAccountId) return
  const owner = state.ownerAccountId
  const stored = queueFileStore.load(owner)
  const storedPhotos = stored?.owner_account_id === owner && Array.isArray(stored.photos) ? stored.photos : []
  const storedBatches = stored?.owner_account_id === owner && Array.isArray(stored.batches) ? stored.batches : []
  state.photos.splice(0, state.photos.length, ...storedPhotos.filter((photo) => String(photo.owner_account_id) === owner).map((photo) => ({
    ...photo,
    status: recoverInterruptedStatus(photo.status),
    progress: photo.status === 'uploading' ? 0 : photo.progress,
  })))
  state.batches.splice(0, state.batches.length, ...storedBatches.filter((batch) => String(batch.owner_account_id) === owner))
  state.hydrated = true
  try { persist(owner) } catch { /* WAL 和上一有效槽仍是可靠恢复源，不能阻断启动。 */ }
  registerNetworkListener()
}

function setOwner(accountId: string | number): void {
  const owner = String(accountId || '')
  if (!owner || (owner === state.ownerAccountId && state.hydrated)) return
  ownerGeneration += 1
  state.ownerAccountId = owner
  state.hydrated = false
  state.running = false
  state.preparing = false
  state.photos.splice(0)
  state.batches.splice(0)
  state.prepareProgress = { current: 0, total: 0, message: '' }
  hydrate()
}

function clearOwner(): void {
  ownerGeneration += 1
  state.ownerAccountId = ''
  state.hydrated = false
  state.running = false
  state.preparing = false
  state.photos.splice(0)
  state.batches.splice(0)
  state.prepareProgress = { current: 0, total: 0, message: '' }
}

async function enqueue(sourcePaths: string[], draft: UploadDraft): Promise<LocalBatch> {
  if (!sourcePaths.length) throw new Error('没有选择照片')
  hydrate()
  const owner = state.ownerAccountId
  const generation = ownerGeneration
  if (!owner) throw new Error('账号尚未就绪，请重新进入小程序')
  state.preparing = true
  state.prepareProgress = { current: 0, total: sourcePaths.length, message: '正在安全保存原图' }
  const batch: LocalBatch = {
    owner_account_id: owner,
    client_batch_id: createUuid(),
    draft: JSON.parse(JSON.stringify(draft)),
    photo_uuids: [],
    committed: false,
    analyzed: false,
    created_at: now(),
  }
  state.batches.unshift(batch)
  try {
    for (let index = 0; index < sourcePaths.length; index += 1) {
      if (!isCurrentOwner(owner, generation)) throw new Error('账号已切换，本次照片处理已停止')
      const sourceSize = await getSourceFileSize(sourcePaths[index])
      if (sourceSize > MAX_ORIGINAL_BYTES) throw new Error('单张原图不能超过 50MB，请选择较小的 JPEG 或 PNG')
      if (!Number.isFinite(sourceSize) || sourceSize <= 0) throw new Error('原图文件为空或无法读取')
      if (queueBytes.value + sourceSize + MAX_PREVIEW_BYTES > MAX_QUEUE_BYTES) throw new Error('本机影像将超过 160MB，请联网完成原图中转后再继续拍摄')
      state.prepareProgress = { current: index + 1, total: sourcePaths.length, message: `正在安全保存第 ${index + 1} 张原图` }
      const photoUuid = createUuid()
      const filename = sourcePaths[index].replace(/\\/g, '/').split('/').pop() || 'photo'
      const photo = recoveryPhoto(owner, batch, { originalPath: '', originalSize: sourceSize, originalFilename: filename }, photoUuid)
      batch.photo_uuids.push(photoUuid)
      let original: { originalPath: string; originalSize: number; originalFilename: string }
      try {
        original = await queueFileStore.stageOriginal(owner, batch, photo, sourcePaths[index], sourceSize)
      } catch (error) {
        const savedError = error as { originalPath?: string; originalSize?: number; originalFilename?: string }
        if (!savedError.originalPath) {
          batch.photo_uuids = batch.photo_uuids.filter((id) => id !== photoUuid)
          throw error
        }
        if (isCurrentOwner(owner, generation)) {
          photo.original_path = savedError.originalPath
          photo.original_size = savedError.originalSize || sourceSize
          photo.original_filename = savedError.originalFilename || filename
          photo.error = error instanceof Error ? error.message : '原图已保存，但复核失败'
          state.photos.unshift(photo)
          try { persist(owner) } catch { /* WAL 已先于原图写入，可在重启后恢复。 */ }
        }
        throw error
      }
      if (!isCurrentOwner(owner, generation)) {
        throw new Error('账号已切换；已保存的原图已由写前清单留在原账号恢复队列')
      }
      photo.original_path = original.originalPath
      photo.original_size = original.originalSize
      photo.original_filename = original.originalFilename
      state.photos.unshift(photo)
      persist(owner)
      if (original.originalSize > MAX_ORIGINAL_BYTES || queueBytes.value + MAX_PREVIEW_BYTES > MAX_QUEUE_BYTES) {
        photo.error = original.originalSize > MAX_ORIGINAL_BYTES
          ? '原图已安全保存，但实际文件超过 50MB，不能上传'
          : '原图已安全保存，但本机影像已达到 160MB'
        photo.retryable = false
        photo.preparation_pending = false
        persist(owner)
        throw new Error(photo.error)
      }
      state.prepareProgress = { current: index + 1, total: sourcePaths.length, message: `正在生成第 ${index + 1} 张本机预览` }
      await completePreparation(photo, generation)
      if (queueBytes.value > MAX_QUEUE_BYTES) throw new Error('本机影像超过 160MB；当前原图和预览均已保留，请先联网中转')
    }
    persist(owner)
    void resume('manual')
    return batch
  } catch (error) {
    if (isCurrentOwner(owner, generation)) {
      if (!batch.photo_uuids.length) {
        const index = state.batches.findIndex((item) => item.client_batch_id === batch.client_batch_id)
        if (index >= 0) state.batches.splice(index, 1)
      } else {
        batch.preparation_error = error instanceof Error ? error.message : '部分照片处理失败'
        void resume('manual')
      }
      persist(owner)
    }
    if (batch.photo_uuids.length) throw new Error(`已有 ${batch.photo_uuids.length} 张原图安全保存；后续照片未加入：${error instanceof Error ? error.message : '处理失败'}`)
    throw error
  } finally {
    if (isCurrentOwner(owner, generation)) {
      state.preparing = false
      state.prepareProgress = { current: 0, total: 0, message: '' }
    }
  }
}

async function confirmBatch(clientBatchId: string, assignments: Array<{ photo_uuid: string; assignment: Assignment; title: string; photo_date: string }>): Promise<void> {
  const batch = state.batches.find((item) => item.client_batch_id === clientBatchId)
  if (!batch?.remote_batch_id || !isCurrentOwner(batch.owner_account_id)) throw new Error('照片尚未上传到服务器，请稍后再确认')
  const payload = assignments.map((item) => ({ photo_uuid: item.photo_uuid, ...item.assignment, title: item.title, photo_date: item.photo_date }))
  try {
    await mobileApi.assignBatch(batch.remote_batch_id, payload)
    await mobileApi.commitBatch(batch.remote_batch_id)
  } catch (error) {
    if (isAuthExpired(error)) void notifyAuthExpired(batch.owner_account_id)
    throw error
  }
  if (!isCurrentOwner(batch.owner_account_id)) return
  assignments.forEach((assignment) => {
    const photo = state.photos.find((item) => item.photo_uuid === assignment.photo_uuid)
    if (!photo) return
    photo.title = assignment.title
    photo.photo_date = assignment.photo_date
    photo.draft.assignment = assignment.assignment
    setStatus(photo, 'desktop_pending')
  })
  batch.committed = true
  persist(batch.owner_account_id)
}

function retryTarget(photo: LocalPhoto): PhotoStatus {
  return automaticRetryTarget(photo.retry_from || 'local_ready')
}

async function retry(photoUuid: string): Promise<void> {
  const photo = state.photos.find((item) => item.photo_uuid === photoUuid)
  if (!photo || photo.status !== 'failed' || photo.retryable === false || !isCurrentOwner(photo.owner_account_id)) return
  if (photo.preparation_pending) {
    await completePreparation(photo)
  } else {
    if (photo.retry_from === 'analyzing') {
      const batch = state.batches.find((item) => item.client_batch_id === photo.client_batch_id)
      if (batch) {
        batch.analysis_requested = false
        batch.analysis_job_id = undefined
      }
    }
    photo.status = retryTarget(photo)
    photo.retry_from = undefined
    photo.progress = photo.status === 'local_ready' ? 0 : 100
    photo.error = undefined
    photo.retryable = undefined
    photo.failure_code = undefined
    photo.auto_retry_pending = undefined
    photo.auto_retry_attempts = undefined
    photo.next_retry_at = undefined
    photo.updated_at = now()
    persist(photo.owner_account_id)
  }
  void resume('manual')
}

async function retryAll(): Promise<void> {
  for (const photo of state.photos.filter((item) => item.status === 'failed' && item.retryable !== false)) await retry(photo.photo_uuid)
}

function recoverAuthFailures(): void {
  state.photos.filter((photo) => photo.status === 'failed' && photo.failure_code === 'AUTH_EXPIRED').forEach((photo) => {
    photo.status = retryTarget(photo)
    photo.retry_from = undefined
    photo.progress = photo.status === 'local_ready' ? 0 : 100
    photo.error = undefined
    photo.retryable = undefined
    photo.failure_code = undefined
    photo.auto_retry_pending = undefined
    photo.auto_retry_attempts = undefined
    photo.next_retry_at = undefined
    photo.updated_at = now()
  })
  persist()
}

function startForegroundPolling(): void {
  state.foreground = true
  if (foregroundTimer) return
  foregroundTimer = setInterval(() => { if (state.ownerAccountId) void resume('manual') }, 30_000)
}

function stopForegroundPolling(): void {
  state.foreground = false
  if (!foregroundTimer) return
  clearInterval(foregroundTimer)
  foregroundTimer = null
}

export const queueBytes = computed(() => retainedQueueBytes(state.photos))
export const pendingCount = computed(() => state.photos.filter((photo) => photo.status !== 'desktop_imported').length)
export const failedCount = computed(() => state.photos.filter((photo) => photo.status === 'failed').length)
export const queueUsagePercent = computed(() => Math.min(100, Math.round((queueBytes.value / MAX_QUEUE_BYTES) * 100)))

export const queueRuntime = {
  state,
  setOwner,
  clearOwner,
  hydrate,
  enqueue,
  resume,
  confirmBatch,
  retry,
  retryAll,
  recoverAuthFailures,
  startForegroundPolling,
  stopForegroundPolling,
  queueBytes,
  pendingCount,
  failedCount,
  queueUsagePercent,
}
