export const MAX_PREVIEW_BYTES = 102_400
export const MAX_TRANSFER_BYTES = 1024 * 1024
export const MAX_ORIGINAL_BYTES = 50 * 1024 * 1024
export const MAX_QUEUE_BYTES = 160 * 1024 * 1024
export const MAX_UPLOAD_CONCURRENCY = 2
// 与服务端 MOBILE_DIRECT_UPLOAD_MAX_BYTES 保持一致。微信原生 uploadFile
// 对普通手机照片比把 ArrayBuffer 塞进 request 更稳定；超过这个边界才启用
// 可断点续传的分片协议。
export const DIRECT_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
export const UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024
export const INITIAL_MAX_EDGE = 1_920
export const TRANSFER_INITIAL_MAX_EDGE = 2_560
export const MIN_JPEG_QUALITY = 30
export const MAX_JPEG_QUALITY = 90
export const RESIZE_FACTOR = 0.85

export interface Dimensions {
  width: number
  height: number
}

export function fitWithinMaxEdge(width: number, height: number, maxEdge = INITIAL_MAX_EDGE): Dimensions {
  const edge = Math.max(width, height)
  if (edge <= maxEdge) return { width: Math.max(1, Math.round(width)), height: Math.max(1, Math.round(height)) }
  const ratio = maxEdge / edge
  return { width: Math.max(1, Math.round(width * ratio)), height: Math.max(1, Math.round(height * ratio)) }
}

export function shrinkDimensions(dimensions: Dimensions): Dimensions {
  return {
    width: Math.max(1, Math.round(dimensions.width * RESIZE_FACTOR)),
    height: Math.max(1, Math.round(dimensions.height * RESIZE_FACTOR)),
  }
}

export function isPreviewWithinLimit(size: number): boolean {
  return Number.isFinite(size) && size > 0 && size <= MAX_PREVIEW_BYTES
}

export function isTransferWithinLimit(size: number): boolean {
  return Number.isFinite(size) && size > 0 && size <= MAX_TRANSFER_BYTES
}

export function isOriginalWithinLimit(size: number): boolean {
  return Number.isFinite(size) && size > 0 && size <= MAX_ORIGINAL_BYTES
}

export function requiresChunkedUpload(size: number): boolean {
  return Number.isFinite(size) && size > DIRECT_UPLOAD_MAX_BYTES
}

export function retainedQueueBytes(items: Array<{ original_path: string; original_size: number; transfer_path?: string; transfer_size?: number; preview_path: string; preview_size: number }>): number {
  return items.reduce((sum, item) => sum
    + (item.original_path ? item.original_size : 0)
    + (item.transfer_path ? Number(item.transfer_size || 0) : 0)
    + (item.preview_path ? item.preview_size : 0), 0)
}

export function canAddToQueue(currentBytes: number, incomingBytes: number): boolean {
  return currentBytes >= 0 && incomingBytes > 0 && currentBytes + incomingBytes <= MAX_QUEUE_BYTES
}

export function findHighestPassingQuality(
  getSize: (quality: number) => number,
  minQuality = MIN_JPEG_QUALITY,
  maxQuality = MAX_JPEG_QUALITY,
  maxBytes = MAX_PREVIEW_BYTES,
): number | null {
  let low = minQuality
  let high = maxQuality
  let best: number | null = null
  while (low <= high) {
    const quality = Math.floor((low + high) / 2)
    if (getSize(quality) <= maxBytes) {
      best = quality
      low = quality + 1
    } else {
      high = quality - 1
    }
  }
  return best
}
