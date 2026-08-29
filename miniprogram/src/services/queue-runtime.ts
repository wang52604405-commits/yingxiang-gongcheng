import { computed, reactive } from 'vue'
import { ApiError } from '@/api/client'
import { mobileApi } from '@/api/mobile'
import type { CreateBatchPayload } from '@/api/contracts'
import type { Assignment, LocalBatch, LocalPhoto, PhotoStatus, UploadDraft } from '@/types/domain'
import { createUuid } from './ids'
import { hashFile } from './sha256'
import { downloadServerPreview, getSourceFileSize, inspectOriginalSource, persistPreparedTransfer, prepareTransferImage } from './image-compression'
import { MAX_ORIGINAL_BYTES, MAX_PREVIEW_BYTES, MAX_QUEUE_BYTES, MAX_TRANSFER_BYTES, MAX_UPLOAD_CONCURRENCY, isTransferWithinLimit, requiresChunkedUpload, retainedQueueBytes } from './queue-policy'
import { canTransition, recoverInterruptedStatus } from './photo-state'
import { notifyAuthExpired } from './auth-expiry-coordinator'
import { queueFileStore } from './queue-storage'
import { UploadPausedError, uploadPhotoInChunks } from './chunk-upload'
import { archiveInfoMessage, isArchiveInfoComplete } from './archive-info'

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
export const IMAGE_PREPARATION_STEP_TIMEOUT_MS = 60_000
const FILE_DELETE_CALLBACK_TIMEOUT_MS = 3_000
const preparationTasks = new Map<string, Promise<boolean>>()
let preparationTail: Promise<void> = Promise.resolve()

class ImagePreparationTimeoutError extends Error {
  readonly code = 'IMAGE_PROCESS_TIMEOUT'
  readonly retryable = true

  constructor(step: string) {
    super(`${step}超时，请点击重试`)
    this.name = 'ImagePreparationTimeoutError'
  }
}

async function runPreparationExclusively<T>(work: () => Promise<T>): Promise<T> {
  const previous = preparationTail
  let release = () => {}
  preparationTail = new Promise<void>((resolve) => { release = resolve })
  await previous
  try {
    return await work()
  } finally {
    release()
  }
}

function withPreparationWatchdog<T>(
  step: string,
  operation: Promise<T>,
  cleanupLateResult?: (value: T) => Promise<void>,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let settled = false
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      reject(new ImagePreparationTimeoutError(step))
    }, IMAGE_PREPARATION_STEP_TIMEOUT_MS)
    operation.then((value) => {
      if (settled) {
        if (cleanupLateResult) void cleanupLateResult(value).catch(() => undefined)
        return
      }
      settled = true
      clearTimeout(timer)
      resolve(value)
    }, (error) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      reject(error)
    })
  })
}

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
    uni.setStorageSync(`engineering-image:queue-count:v3:${owner}`, state.photos.filter((photo) => !['desktop_imported', 'local_deleted'].includes(photo.status)).length)
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
    let settled = false
    const finish = (removed: boolean) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(removed)
    }
    const timer = setTimeout(() => finish(false), FILE_DELETE_CALLBACK_TIMEOUT_MS)
    wxApi.getFileSystemManager().unlink({
      filePath: path,
      success: () => finish(true),
      fail: (error: { errMsg?: string }) => finish(String(error?.errMsg || '').includes('no such file')),
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
  return error.statusCode === 403
    || ['project_access_revoked', 'project_permission_denied', 'project_access_denied', 'project_not_found'].includes(String(error.code || '').toLowerCase())
}

function hasPermanentArchiveInfoFailure(batch: LocalBatch | undefined): boolean {
  return Boolean(
    batch
    && batch.archive_info_sync_retryable === false
    && batch.archive_info_sync_failure_code,
  )
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
  const errorShape = error && typeof error === 'object' ? error as { code?: unknown; retryable?: unknown } : undefined
  const failureCode = isAuthExpired(error)
    ? 'AUTH_EXPIRED'
    : error instanceof ApiError
      ? error.code
      : typeof errorShape?.code === 'string'
        ? errorShape.code
        : undefined
  photo.retry_from = retryFrom
  photo.status = 'failed'
  const message = isProjectAccessRevoked(error) ? '已无此工程采集权限；1MB 归档图仍保存在本机' : errorMessage(error)
  photo.error = preparation ? `原图已安全保存；${message}` : message
  photo.failure_code = failureCode
  photo.retryable = isProjectAccessRevoked(error)
    ? false
    : isAuthExpired(error)
      ? true
      : typeof errorShape?.retryable === 'boolean'
        ? errorShape.retryable
        : true
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

async function cleanupTransfer(photo: LocalPhoto): Promise<void> {
  if (!isCurrentOwner(photo.owner_account_id) || !photo.transfer_path) return
  const removed = await removeSavedFile(photo.transfer_path)
  if (!isCurrentOwner(photo.owner_account_id) || !removed) return
  photo.transfer_path = ''
  persist(photo.owner_account_id)
}

function markArchiveInfoAccessRevoked(batch: LocalBatch, photos: LocalPhoto[], error: unknown): void {
  const owner = batch.owner_account_id
  if (!isCurrentOwner(owner)) return
  const failureCode = error instanceof ApiError ? error.code : 'project_access_revoked'
  batch.archive_info_sync_pending = undefined
  batch.archive_info_sync_error = '已无此工程采集权限；已停止自动同步，服务器照片和本机预览均已保留'
  batch.archive_info_sync_failure_code = failureCode
  batch.archive_info_sync_retryable = false
  photos.filter((photo) => ['local_ready', 'server_saved'].includes(photo.status)).forEach((photo) => {
    const retryFrom = photo.status === 'server_saved' ? 'server_saved' : 'local_ready'
    markFailed(photo, error, retryFrom)
    photo.error = photo.status === 'failed' && retryFrom === 'server_saved'
      ? '已无此工程采集权限；服务器照片和本机100KB预览均已保留'
      : '已无此工程采集权限；本机1MB归档图和100KB预览均已保留'
    photo.failure_code = failureCode
    photo.retryable = false
    photo.updated_at = now()
  })
  persist(owner)
}

function markArchiveInfoRequired(photo: LocalPhoto, draft: UploadDraft): void {
  markFailed(photo, new Error(`${archiveInfoMessage(draft)}；1MB 归档图仍保存在本机`), 'local_ready')
  photo.failure_code = 'ARCHIVE_INFO_REQUIRED'
  photo.retryable = false
  persist(photo.owner_account_id)
}

function hasValidTransfer(photo: LocalPhoto): boolean {
  return Boolean(
    photo.transfer_path
    && photo.transfer_sha256
    && photo.transfer_filename
    && isTransferWithinLimit(Number(photo.transfer_size || 0)),
  )
}

function markTransferInvalid(photo: LocalPhoto): void {
  markFailed(photo, new Error('1MB 归档图不完整或超过限制；已停止提交，现有影像仍保存在本机'), 'local_ready')
  photo.failure_code = 'TRANSFER_FILE_INVALID'
  photo.retryable = false
  persist(photo.owner_account_id)
}

async function markDesktopImported(photo: LocalPhoto): Promise<void> {
  if (!isCurrentOwner(photo.owner_account_id)) return
  if (photo.status !== 'desktop_imported') setStatus(photo, 'desktop_imported', !canTransition(photo.status, 'desktop_imported'))
  await cleanupOriginal(photo)
  await cleanupTransfer(photo)
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
    transfer_path: '',
    transfer_size: 0,
    transfer_sha256: '',
    transfer_filename: '',
    transfer_width: 0,
    transfer_height: 0,
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
    error: '原图已安全保存，正在准备 1MB 上传图',
    retryable: true,
    preparation_pending: true,
    created_at: createdAt,
    updated_at: createdAt,
  }
}

async function completePreparationOnce(photo: LocalPhoto, generation = ownerGeneration): Promise<boolean> {
  const owner = photo.owner_account_id
  if (!isCurrentOwner(owner, generation) || !photo.original_path) return false
  try {
    if (!photo.original_mime_type || !photo.width || !photo.height) {
      const inspected = await withPreparationWatchdog(
        '读取原图信息',
        inspectOriginalSource(photo.original_path, photo.original_filename, photo.client_captured_at),
      )
      if (!isCurrentOwner(owner, generation)) return false
      photo.width = inspected.width
      photo.height = inspected.height
      photo.orientation = inspected.orientation
      photo.client_captured_at = inspected.capturedAt
      photo.photo_date = inspected.capturedAt.slice(0, 10)
      photo.original_mime_type = inspected.originalMimeType
      persist(owner)
    }
    if (!photo.transfer_path) {
      const prepared = await withPreparationWatchdog(
        '生成 1MB 归档图',
        prepareTransferImage(photo.original_path, photo.original_filename),
        async (late) => { await removeGeneratedFile(late.transferTempPath) },
      )
      if (!isCurrentOwner(owner, generation)) {
        await removeGeneratedFile(prepared.transferTempPath)
        return false
      }
      let saved: Awaited<ReturnType<typeof persistPreparedTransfer>>
      try {
        saved = await withPreparationWatchdog(
          '保存 1MB 归档图',
          persistPreparedTransfer(prepared),
          async (late) => { await removeSavedFile(late.transferPath) },
        )
      } finally {
        await removeGeneratedFile(prepared.transferTempPath)
      }
      if (!isCurrentOwner(owner, generation)) {
        await removeSavedFile(saved.transferPath)
        return false
      }
      photo.transfer_path = saved.transferPath
      photo.transfer_size = saved.transferSize
      photo.transfer_filename = saved.transferFilename
      photo.transfer_width = saved.transferWidth
      photo.transfer_height = saved.transferHeight
      persist(owner)
    }
    if (!isTransferWithinLimit(Number(photo.transfer_size || 0))) {
      throw new Error('归档图超过 1MB，已停止上传')
    }
    if (!photo.transfer_sha256) {
      photo.transfer_sha256 = await withPreparationWatchdog('校验 1MB 归档图', hashFile(photo.transfer_path))
      if (!isCurrentOwner(owner, generation)) return false
      persist(owner)
    }
    // 100KB 预览由服务器在收到 1MB 上传图后生成。此前在手机端再次压缩
    // 大图，会让部分机型长期卡在“正在生成本机预览”，照片也无法上传。
    // 上传成功后 tryRecoverServerPreview 会只下载服务器生成的合规预览。
    photo.preparation_pending = false
    setStatus(photo, 'local_ready', true)
    await cleanupOriginal(photo)
    return true
  } catch (error) {
    markFailed(photo, error, 'local_ready', true)
    return false
  }
}

function completePreparation(photo: LocalPhoto, generation = ownerGeneration): Promise<boolean> {
  const key = `${generation}:${photo.owner_account_id}:${photo.photo_uuid}`
  const existing = preparationTasks.get(key)
  if (existing) return existing
  const task = runPreparationExclusively(() => completePreparationOnce(photo, generation))
    .finally(() => {
      if (preparationTasks.get(key) === task) preparationTasks.delete(key)
    })
  preparationTasks.set(key, task)
  return task
}

async function repairIncompletePhotos(generation: number): Promise<void> {
  if (state.preparing) return
  const items = state.photos.filter((photo) => (
    photo.preparation_pending
    && photo.original_path
    && photo.failure_code !== 'IMAGE_PROCESS_TIMEOUT'
  ))
  for (const photo of items) {
    if (state.preparing || !isCurrentOwner(photo.owner_account_id, generation)) return
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
  if (!hasValidTransfer(photo)) {
    markTransferInvalid(photo)
    return
  }
  const transferPath = photo.transfer_path!
  const transferSha256 = photo.transfer_sha256!
  const transferFilename = photo.transfer_filename!
  try {
    beginAutomaticRetryAttempt(photo)
    setStatus(photo, 'uploading')
    photo.progress = 1
    persist(owner)
    const metadata = {
      photo_uuid: photo.photo_uuid,
      client_captured_at: photo.client_captured_at,
      orientation: photo.orientation,
      width: Number(photo.transfer_width || photo.width),
      height: Number(photo.transfer_height || photo.height),
      sha256: transferSha256,
      original_size_bytes: Number(photo.transfer_size),
      original_filename: transferFilename,
      original_mime_type: 'image/jpeg' as const,
      title: photo.title,
      photo_date: photo.photo_date,
      capture_source: photo.draft.capture_source,
      transfer_profile: 'jpeg_1m' as const,
    }
    if (!requiresChunkedUpload(Number(photo.transfer_size))) {
      photo.upload_mode = 'direct'
      persist(owner)
      await mobileApi.uploadPhoto(batch.remote_batch_id!, transferPath, metadata, (progress) => {
        if (isCurrentOwner(owner, generation)) photo.progress = progress
      })
    } else {
      photo.upload_mode = 'chunked'
      persist(owner)
      await uploadPhotoInChunks({
        batchId: batch.remote_batch_id!,
        filePath: transferPath,
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
    await cleanupTransfer(photo)
  } catch (error) {
    if (!isCurrentOwner(owner, generation)) return
    if (!state.online || error instanceof UploadPausedError) {
      setStatus(photo, 'local_ready')
      return
    }
    if (!scheduleAutomaticRetry(photo, error, 'uploading')) markFailed(photo, error, 'uploading')
    if (isAuthExpired(error)) void notifyAuthExpired(owner)
  } finally {
    if (isCurrentOwner(owner, generation) && String(photo.status) === 'uploading') {
      markFailed(photo, new ApiError('照片上传未完成，1MB 归档图仍保存在本机，请重试', 'UPLOAD_INTERRUPTED', true), 'uploading')
    }
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
  if (photo.status === 'local_deleted') return
  if (!(remoteStatus in REMOTE_STATUS_RANK)) return
  const target = remoteStatus as PhotoStatus
  const currentRank = REMOTE_STATUS_RANK[photo.status] || 0
  const targetRank = REMOTE_STATUS_RANK[target] || 0
  const failedDuringUpload = photo.status === 'failed' && ['local_ready', 'uploading'].includes(photo.retry_from || 'local_ready') && !photo.preparation_pending
  if (targetRank > currentRank || failedDuringUpload) setStatus(photo, target, !canTransition(photo.status, target))
  if (targetRank >= 1) {
    await tryRecoverServerPreview(photo, ownerGeneration)
    await cleanupOriginal(photo)
    await cleanupTransfer(photo)
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
      if (!hasPermanentArchiveInfoFailure(batch)) await applyRemoteStatus(local, remote.status)
    }
    if (localPhotos.every((photo) => ['needs_review', 'desktop_pending', 'desktop_imported', 'local_deleted'].includes(photo.status))) batch.analyzed = batch.draft.mode === 'auto' || batch.analyzed
    if (localPhotos.every((photo) => ['desktop_pending', 'desktop_imported', 'local_deleted'].includes(photo.status))) batch.committed = true
    persist(owner)
  } catch (error) {
    // 状态刷新是尽力而为；绝不把服务器已保存的照片降级。
    if (isAuthExpired(error)) void notifyAuthExpired(owner)
  }
}

async function syncPendingArchiveInfo(batch: LocalBatch, photos: LocalPhoto[], generation: number): Promise<boolean> {
  if (!batch.archive_info_sync_pending) return true
  const owner = batch.owner_account_id
  if (!isCurrentOwner(owner, generation)) return false
  if (!batch.remote_batch_id) {
    batch.archive_info_sync_pending = undefined
    persist(owner)
    return true
  }
  if (!batch.draft.assignment || !isArchiveInfoComplete(batch.draft)) return false
  const retryPhotos = photos.filter((photo) => ['local_ready', 'server_saved'].includes(photo.status))
  if (retryPhotos.some((photo) => !isAutomaticRetryDue(photo))) return false
  try {
    retryPhotos.forEach(beginAutomaticRetryAttempt)
    persist(owner)
    await mobileApi.updateBatchArchiveInfo(batch.remote_batch_id, batch.draft.assignment)
    if (!isCurrentOwner(owner, generation)) return false
    batch.archive_info_sync_pending = undefined
    batch.archive_info_sync_error = undefined
    batch.archive_info_sync_failure_code = undefined
    batch.archive_info_sync_retryable = undefined
    persist(owner)
    return true
  } catch (error) {
    if (!isCurrentOwner(owner, generation)) return false
    if (isProjectAccessRevoked(error)) {
      markArchiveInfoAccessRevoked(batch, photos, error)
      return false
    }
    retryPhotos.forEach((photo) => {
      const retryFrom = photo.status === 'server_saved' ? 'server_saved' : 'local_ready'
      if (!scheduleAutomaticRetry(photo, error, retryFrom) && photo.status === 'local_ready') markFailed(photo, error, retryFrom)
    })
    persist(owner)
    if (isAuthExpired(error)) void notifyAuthExpired(owner)
    return false
  }
}

async function processBatch(batch: LocalBatch, generation: number): Promise<void> {
  const owner = batch.owner_account_id
  if (!isCurrentOwner(owner, generation)) return
  if (hasPermanentArchiveInfoFailure(batch)) return
  const photos = state.photos.filter((photo) => batch.photo_uuids.includes(photo.photo_uuid))
  if (!await syncPendingArchiveInfo(batch, photos, generation)) return
  const ready = photos.filter((photo) => photo.status === 'local_ready' && isAutomaticRetryDue(photo))
  const invalidTransfers = ready.filter((photo) => !hasValidTransfer(photo))
  invalidTransfers.forEach(markTransferInvalid)
  const uploadable = ready.filter((photo) => hasValidTransfer(photo))
  if (uploadable.length && !isArchiveInfoComplete(batch.draft)) {
    uploadable.forEach((photo) => markArchiveInfoRequired(photo, batch.draft))
    return
  }
  if (!batch.remote_batch_id && !uploadable.length) return
  if (!batch.remote_batch_id) {
    const payload: CreateBatchPayload = {
      client_batch_id: batch.client_batch_id,
      project_id: batch.draft.project_id,
      scope: batch.draft.scope,
      category: batch.draft.category,
      mode: batch.draft.mode,
      capture_source: batch.draft.capture_source,
      transfer_profile: batch.draft.transfer_profile || 'jpeg_1m',
      assignment: batch.draft.assignment,
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
  if (!owner || state.preparing || state.running || !state.foreground) return
  state.running = true
  try {
    await repairIncompletePhotos(generation)
    state.online = await getNetworkType()
    if (!isCurrentOwner(owner, generation) || !state.online || !state.foreground || state.preparing) return
    for (const batch of [...state.batches]) {
      if (!isCurrentOwner(owner, generation) || !state.online) break
      const batchPhotos = state.photos.filter((photo) => batch.photo_uuids.includes(photo.photo_uuid))
      if (batchPhotos.length && batchPhotos.every((photo) => ['desktop_imported', 'local_deleted'].includes(photo.status))) continue
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
      await cleanupTransfer(photo)
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
  state.photos.splice(0, state.photos.length, ...storedPhotos.filter((photo) => String(photo.owner_account_id) === owner).map((photo) => {
    // 旧版本在“本机预览”步骤超时的照片，1MB 上传图已经准备完成。
    // 升级后直接恢复为待上传，不要求用户删除重拍。
    const previewOnlyTimeout = Boolean(
      photo.status === 'failed'
      && photo.failure_code === 'IMAGE_PROCESS_TIMEOUT'
      && photo.retry_from === 'local_ready'
      && photo.transfer_path
      && photo.transfer_sha256
      && photo.transfer_filename
      && isTransferWithinLimit(Number(photo.transfer_size || 0))
      && !photo.preview_path,
    )
    const recoveredStatus = recoverInterruptedStatus(photo.status)
    const needsTransferMigration = Boolean(photo.original_path && !photo.transfer_path && (
      ['local_ready', 'uploading'].includes(photo.status)
      || (photo.status === 'failed' && ['local_ready', 'uploading'].includes(photo.retry_from || 'local_ready'))
    ))
    return {
      ...photo,
      draft: { ...photo.draft, transfer_profile: photo.draft.transfer_profile || 'jpeg_1m' },
      status: previewOnlyTimeout ? 'local_ready' : recoveredStatus,
      progress: photo.status === 'uploading' ? 0 : photo.progress,
      preparation_pending: previewOnlyTimeout ? false : (photo.preparation_pending || needsTransferMigration),
      error: previewOnlyTimeout ? undefined : photo.error,
      retryable: previewOnlyTimeout ? undefined : photo.retryable,
      retry_from: previewOnlyTimeout ? undefined : photo.retry_from,
      failure_code: previewOnlyTimeout ? undefined : photo.failure_code,
    }
  }))
  state.batches.splice(0, state.batches.length, ...storedBatches.filter((batch) => String(batch.owner_account_id) === owner).map((batch) => ({
    ...batch,
    draft: { ...batch.draft, transfer_profile: batch.draft.transfer_profile || 'jpeg_1m' },
  })))
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
  if (state.preparing) throw new Error('照片正在准备，请稍候再次选择')
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
      const sourceSize = await withPreparationWatchdog('读取原图大小', getSourceFileSize(sourcePaths[index]))
      if (sourceSize > MAX_ORIGINAL_BYTES) throw new Error('单张原图不能超过 50MB，请选择较小的 JPEG 或 PNG')
      if (!Number.isFinite(sourceSize) || sourceSize <= 0) throw new Error('原图文件为空或无法读取')
      if (queueBytes.value + sourceSize + MAX_TRANSFER_BYTES + MAX_PREVIEW_BYTES > MAX_QUEUE_BYTES) throw new Error('本机影像将超过 160MB，请联网完成传输后再继续拍摄')
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
      if (original.originalSize > MAX_ORIGINAL_BYTES || queueBytes.value + MAX_TRANSFER_BYTES + MAX_PREVIEW_BYTES > MAX_QUEUE_BYTES) {
        photo.error = original.originalSize > MAX_ORIGINAL_BYTES
          ? '原图已安全保存，但实际文件超过 50MB，不能上传'
          : '原图已安全保存，但本机影像已达到 160MB'
        photo.retryable = false
        photo.preparation_pending = false
        persist(owner)
        throw new Error(photo.error)
      }
      state.prepareProgress = { current: index + 1, total: sourcePaths.length, message: `正在准备第 ${index + 1} 张影像` }
      await completePreparation(photo, generation)
      if (queueBytes.value > MAX_QUEUE_BYTES) throw new Error('本机影像超过 160MB；当前原图和预览均已保留，请先联网中转')
    }
    persist(owner)
    return batch
  } catch (error) {
    if (isCurrentOwner(owner, generation)) {
      if (!batch.photo_uuids.length) {
        const index = state.batches.findIndex((item) => item.client_batch_id === batch.client_batch_id)
        if (index >= 0) state.batches.splice(index, 1)
      } else {
        batch.preparation_error = error instanceof Error ? error.message : '部分照片处理失败'
      }
      persist(owner)
    }
    if (batch.photo_uuids.length) throw new Error(`已有 ${batch.photo_uuids.length} 张原图安全保存；后续照片未加入：${error instanceof Error ? error.message : '处理失败'}`)
    throw error
  } finally {
    if (isCurrentOwner(owner, generation)) {
      state.preparing = false
      state.prepareProgress = { current: 0, total: 0, message: '' }
      if (batch.photo_uuids.length) void resume('manual')
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

function canManuallyRetry(photoUuid: string): boolean {
  const photo = state.photos.find((item) => item.photo_uuid === photoUuid)
  if (!photo || photo.status !== 'failed' || !isCurrentOwner(photo.owner_account_id)) return false
  if (photo.retryable !== false) return true
  const batch = state.batches.find((item) => item.client_batch_id === photo.client_batch_id)
  return Boolean(batch && hasPermanentArchiveInfoFailure(batch)
    && photo.failure_code === batch.archive_info_sync_failure_code
  )
}

function clearPermanentArchiveInfoFailure(batch: LocalBatch): void {
  const failureCode = batch.archive_info_sync_failure_code
  batch.archive_info_sync_pending = batch.remote_batch_id ? true : undefined
  batch.archive_info_sync_error = undefined
  batch.archive_info_sync_failure_code = undefined
  batch.archive_info_sync_retryable = undefined
  state.photos.filter((photo) => (
    batch.photo_uuids.includes(photo.photo_uuid)
    && photo.status === 'failed'
    && photo.failure_code === failureCode
  )).forEach((photo) => {
    photo.status = retryTarget(photo)
    photo.retry_from = undefined
    photo.progress = photo.status === 'local_ready' ? 0 : 100
    photo.error = undefined
    photo.failure_code = undefined
    photo.retryable = undefined
    photo.auto_retry_pending = undefined
    photo.auto_retry_attempts = undefined
    photo.next_retry_at = undefined
    photo.updated_at = now()
  })
}

async function removeGeneratedFile(path: string): Promise<void> {
  if (!path) return
  const wxApi = (globalThis as { wx?: any }).wx
  if (!wxApi?.getFileSystemManager) return
  await new Promise<void>((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve()
    }
    const timer = setTimeout(finish, FILE_DELETE_CALLBACK_TIMEOUT_MS)
    wxApi.getFileSystemManager().unlink({ filePath: path, success: finish, fail: finish })
  })
}

function completeArchiveInfo(clientBatchId: string, projectName: string, assignment: Assignment): void {
  const batch = state.batches.find((item) => item.client_batch_id === clientBatchId)
  if (!batch || !isCurrentOwner(batch.owner_account_id)) throw new Error('本机队列中没有找到这批照片')
  const hadPermanentArchiveInfoFailure = hasPermanentArchiveInfoFailure(batch)
  const permanentFailureCode = batch.archive_info_sync_failure_code
  batch.draft = {
    ...batch.draft,
    project_name: String(projectName || batch.draft.project_name || ''),
    transfer_profile: 'jpeg_1m',
    assignment: { ...assignment },
  }
  if (!isArchiveInfoComplete(batch.draft)) throw new Error(archiveInfoMessage(batch.draft))
  const batchPhotos = state.photos.filter((photo) => batch.photo_uuids.includes(photo.photo_uuid))
  const repairedPhotos = batchPhotos.filter((photo) => photo.status === 'failed' && (
    photo.failure_code === 'ARCHIVE_INFO_REQUIRED'
    || (hadPermanentArchiveInfoFailure && photo.failure_code === permanentFailureCode)
  ))
  batch.archive_info_sync_pending = batch.remote_batch_id ? true : undefined
  batch.archive_info_sync_error = undefined
  batch.archive_info_sync_failure_code = undefined
  batch.archive_info_sync_retryable = undefined
  if (repairedPhotos.length && batch.draft.mode === 'direct') batch.committed = false
  if (repairedPhotos.length && batch.draft.mode === 'auto') {
    batch.analyzed = false
    batch.analysis_requested = false
    batch.analysis_job_id = undefined
  }
  batchPhotos.forEach((photo) => {
    photo.draft = JSON.parse(JSON.stringify(batch.draft))
    if (repairedPhotos.includes(photo)) {
      photo.status = photo.failure_code === 'ARCHIVE_INFO_REQUIRED' ? 'local_ready' : retryTarget(photo)
      photo.retry_from = undefined
      photo.progress = 0
      photo.error = undefined
      photo.failure_code = undefined
      photo.retryable = undefined
      photo.auto_retry_pending = undefined
      photo.auto_retry_attempts = undefined
      photo.next_retry_at = undefined
      photo.updated_at = now()
    }
  })
  persist(batch.owner_account_id)
  void resume('manual')
}

async function retry(photoUuid: string): Promise<void> {
  const photo = state.photos.find((item) => item.photo_uuid === photoUuid)
  if (!photo || !canManuallyRetry(photoUuid)) return
  const batch = state.batches.find((item) => item.client_batch_id === photo.client_batch_id)
  if (batch && hasPermanentArchiveInfoFailure(batch)) {
    clearPermanentArchiveInfoFailure(batch)
    persist(photo.owner_account_id)
    await resume('manual')
    return
  }
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

async function deleteFailed(photoUuid: string): Promise<void> {
  const photo = state.photos.find((item) => item.photo_uuid === photoUuid)
  if (!photo || !isCurrentOwner(photo.owner_account_id)) throw new Error('本机队列中没有找到这张照片')
  if (photo.status !== 'failed') throw new Error('只有处理失败的照片可以从本机删除')

  const paths = [photo.original_path, photo.transfer_path, photo.preview_path].filter((path): path is string => Boolean(path))
  const removed = await Promise.all(paths.map((path) => removeSavedFile(path)))
  if (removed.some((ok) => !ok)) throw new Error('本机暂存文件删除失败，请稍后重试')

  photo.original_path = ''
  photo.original_size = 0
  photo.original_sha256 = ''
  photo.original_filename = ''
  photo.original_mime_type = ''
  photo.original_removed = true
  photo.transfer_path = ''
  photo.transfer_size = 0
  photo.transfer_sha256 = ''
  photo.transfer_filename = ''
  photo.transfer_width = 0
  photo.transfer_height = 0
  photo.preview_path = ''
  photo.preview_size = 0
  photo.preview_sha256 = ''
  photo.preview_width = 0
  photo.preview_height = 0
  photo.preparation_pending = false
  photo.preview_recovery_pending = false
  photo.preview_error = undefined
  photo.preview_retry_attempts = undefined
  photo.preview_next_retry_at = undefined
  photo.local_deleted_at = now()
  setStatus(photo, 'local_deleted')
  queueFileStore.clearOriginalWal(photo.owner_account_id, photo.photo_uuid)
  persist(photo.owner_account_id)
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
export const pendingCount = computed(() => state.photos.filter((photo) => !['desktop_imported', 'local_deleted'].includes(photo.status)).length)
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
  completeArchiveInfo,
  canManuallyRetry,
  retry,
  retryAll,
  deleteFailed,
  recoverAuthFailures,
  startForegroundPolling,
  stopForegroundPolling,
  queueBytes,
  pendingCount,
  failedCount,
  queueUsagePercent,
}
