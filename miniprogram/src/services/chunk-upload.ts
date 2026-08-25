import { mobileApi } from '@/api/mobile'
import type { PhotoUploadMetadata } from '@/api/contracts'
import { ApiError } from '@/api/client'
import { UPLOAD_CHUNK_BYTES } from './queue-policy'
import { readFileChunk, sha256Hex } from './sha256'

export class UploadPausedError extends Error {
  constructor() {
    super('上传已随小程序进入后台暂停，返回前台后会继续')
    this.name = 'UploadPausedError'
  }
}

export interface ChunkUploadCheckpoint {
  uploadId: string
  chunkSize: number
  totalChunks: number
  uploadedChunks: number[]
}

interface ChunkUploadOptions {
  batchId: string
  filePath: string
  metadata: PhotoUploadMetadata
  previousUploadedChunks?: number[]
  shouldContinue: () => boolean
  onCheckpoint: (checkpoint: ChunkUploadCheckpoint) => void
  onProgress?: (progress: number) => void
}

function normalizedIndices(values: number[], total: number): number[] {
  return [...new Set(values.map(Number).filter((value) => Number.isInteger(value) && value >= 0 && value < total))].sort((a, b) => a - b)
}

function progressFor(indices: number[], totalBytes: number, chunkSize: number): number {
  const uploaded = indices.reduce((sum, index) => sum + Math.min(chunkSize, totalBytes - index * chunkSize), 0)
  return Math.max(0, Math.min(99, Math.floor((uploaded / totalBytes) * 100)))
}

export async function uploadPhotoInChunks(options: ChunkUploadOptions): Promise<unknown> {
  const totalChunks = Math.ceil(options.metadata.original_size_bytes / UPLOAD_CHUNK_BYTES)
  let initialized = await mobileApi.initChunkedUpload(options.batchId, options.metadata, UPLOAD_CHUNK_BYTES)
  const finishFromExisting = (response: typeof initialized): boolean => {
    if (!['completed', 'finalized', 'server_saved'].includes(response.upload.status)) return false
    options.onCheckpoint({
      uploadId: response.upload.upload_id,
      chunkSize: UPLOAD_CHUNK_BYTES,
      totalChunks,
      uploadedChunks: Array.from({ length: totalChunks }, (_, index) => index),
    })
    options.onProgress?.(100)
    return true
  }
  if (finishFromExisting(initialized)) return initialized
  if (!options.shouldContinue()) throw new UploadPausedError()
  let queried: Awaited<ReturnType<typeof mobileApi.chunkedUpload>> | null = null
  for (let attempt = 0; attempt < 2 && !queried; attempt += 1) {
    try {
      queried = await mobileApi.chunkedUpload(options.batchId, options.metadata.photo_uuid)
    } catch (error) {
      if (!(error instanceof ApiError) || error.statusCode !== 404 || attempt > 0) throw error
      // finalize 后服务端可以清理临时会话；再次 init 会幂等返回已保存照片，或建立新的空会话。
      initialized = await mobileApi.initChunkedUpload(options.batchId, options.metadata, UPLOAD_CHUNK_BYTES)
      if (finishFromExisting(initialized)) return initialized
    }
  }
  if (!queried) throw new Error('无法取得照片分片会话')
  const uploadId = queried.upload.upload_id || initialized.upload.upload_id
  // 服务端查询结果是唯一权威。上传会话过期后，本机旧 checkpoint 绝不能让缺失分片被跳过。
  let uploaded = normalizedIndices(queried.upload.uploaded_chunks, totalChunks)
  options.onCheckpoint({ uploadId, chunkSize: UPLOAD_CHUNK_BYTES, totalChunks, uploadedChunks: uploaded })
  options.onProgress?.(progressFor(uploaded, options.metadata.original_size_bytes, UPLOAD_CHUNK_BYTES))

  for (let index = 0; index < totalChunks; index += 1) {
    if (uploaded.includes(index)) continue
    if (!options.shouldContinue()) throw new UploadPausedError()
    const position = index * UPLOAD_CHUNK_BYTES
    const length = Math.min(UPLOAD_CHUNK_BYTES, options.metadata.original_size_bytes - position)
    const bytes = await readFileChunk(options.filePath, position, length)
    if (bytes.byteLength !== length) throw new Error(`原图第 ${index + 1} 片读取不完整`)
    const result = await mobileApi.uploadChunk(options.batchId, options.metadata.photo_uuid, index, bytes, sha256Hex(bytes))
    uploaded = normalizedIndices([...uploaded, index, ...result.uploaded_chunks], totalChunks)
    options.onCheckpoint({ uploadId, chunkSize: UPLOAD_CHUNK_BYTES, totalChunks, uploadedChunks: uploaded })
    options.onProgress?.(progressFor(uploaded, options.metadata.original_size_bytes, UPLOAD_CHUNK_BYTES))
  }
  if (!options.shouldContinue()) throw new UploadPausedError()
  const result = await mobileApi.finalizeChunkedUpload(options.batchId, options.metadata, totalChunks)
  options.onProgress?.(100)
  return result
}
