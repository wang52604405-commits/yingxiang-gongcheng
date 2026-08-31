import { describe, expect, it } from 'vitest'
import {
  MAX_PREVIEW_BYTES,
  MAX_TRANSFER_BYTES,
  MAX_ORIGINAL_BYTES,
  MAX_QUEUE_BYTES,
  MAX_UPLOAD_CONCURRENCY,
  canAddToQueue,
  findHighestPassingQuality,
  fitWithinMaxEdge,
  isPreviewWithinLimit,
  isTransferWithinLimit,
  isOriginalWithinLimit,
  retainedQueueBytes,
  shrinkDimensions,
  requiresChunkedUpload,
} from '@/services/queue-policy'

describe('照片大小与本机队列策略', () => {
  it('本机 JPEG 预览硬限制为 102400 字节', () => {
    expect(MAX_PREVIEW_BYTES).toBe(102_400)
    expect(isPreviewWithinLimit(102_400)).toBe(true)
    expect(isPreviewWithinLimit(102_401)).toBe(false)
  })

  it('最终归档 JPEG 恰好 1048576 字节可传，多一个字节即拒绝', () => {
    expect(MAX_TRANSFER_BYTES).toBe(1_048_576)
    expect(isTransferWithinLimit(1_048_576)).toBe(true)
    expect(isTransferWithinLimit(1_048_577)).toBe(false)
  })

  it('原图安全中转硬限制为 50MB', () => {
    expect(MAX_ORIGINAL_BYTES).toBe(50 * 1024 * 1024)
    expect(isOriginalWithinLimit(MAX_ORIGINAL_BYTES)).toBe(true)
    expect(isOriginalWithinLimit(MAX_ORIGINAL_BYTES + 1)).toBe(false)
  })

  it('10MiB 以内用微信原生 uploadFile，超过一个字节才走分片', () => {
    expect(requiresChunkedUpload(10 * 1024 * 1024)).toBe(false)
    expect(requiresChunkedUpload(10 * 1024 * 1024 + 1)).toBe(true)
  })

  it('队列达到 160MB 后拒绝继续加入', () => {
    expect(MAX_QUEUE_BYTES).toBe(160 * 1024 * 1024)
    expect(canAddToQueue(MAX_QUEUE_BYTES - 100, 100)).toBe(true)
    expect(canAddToQueue(MAX_QUEUE_BYTES - 100, 101)).toBe(false)
  })

  it('固定并发为 2，并优先保留最高可用质量', () => {
    expect(MAX_UPLOAD_CONCURRENCY).toBe(2)
    expect(findHighestPassingQuality((quality) => quality * 2_000)).toBe(51)
  })

  it('最长边从 1920 开始，失败后每轮缩小 15%', () => {
    expect(fitWithinMaxEdge(4_000, 3_000)).toEqual({ width: 1_920, height: 1_440 })
    expect(shrinkDimensions({ width: 1_920, height: 1_440 })).toEqual({ width: 1_632, height: 1_224 })
  })

  it('容量统计包含准备中的大图、1MiB 归档图和长期留存预览', () => {
    expect(retainedQueueBytes([
      { original_path: '/user/a.jpg', original_size: 5_000_000, transfer_path: '/user/a-transfer.jpg', transfer_size: 900_000, preview_path: '/user/a-preview.jpg', preview_size: 90_000 },
      { original_path: '', original_size: 6_000_000, transfer_path: '/user/b-transfer.jpg', transfer_size: 800_000, preview_path: '/user/b-preview.jpg', preview_size: 80_000 },
    ])).toBe(6_870_000)
  })
})
