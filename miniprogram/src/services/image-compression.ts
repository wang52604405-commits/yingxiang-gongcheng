import {
  MAX_JPEG_QUALITY,
  MAX_PREVIEW_BYTES,
  MAX_TRANSFER_BYTES,
  MIN_JPEG_QUALITY,
  fitWithinMaxEdge,
  isPreviewWithinLimit,
  isTransferWithinLimit,
  shrinkDimensions,
  TRANSFER_INITIAL_MAX_EDGE,
  type Dimensions,
} from './queue-policy'
import { readFilePrefix } from './sha256'

interface ImageInfo {
  path: string
  width: number
  height: number
  orientation: string | number
  type?: string
}

export type SupportedOriginalMimeType = 'image/jpeg' | 'image/png'

export interface PersistedOriginal {
  originalPath: string
  originalSize: number
  originalFilename: string
}

export interface OriginalInspection {
  originalMimeType: SupportedOriginalMimeType
  width: number
  height: number
  orientation: number
  capturedAt: string
}

export interface PreparedPreview {
  originalMimeType: SupportedOriginalMimeType
  previewTempPath: string
  previewSize: number
  previewWidth: number
  previewHeight: number
  width: number
  height: number
  orientation: number
  capturedAt: string
}

export interface PersistedPreview extends Omit<PreparedPreview, 'previewTempPath'> {
  previewPath: string
}

export interface PreparedTransfer {
  transferTempPath: string
  transferSize: number
  transferWidth: number
  transferHeight: number
  transferFilename: string
}

export interface PersistedTransfer extends Omit<PreparedTransfer, 'transferTempPath'> {
  transferPath: string
}

export interface CompressionAdapter {
  getImageInfo(path: string): Promise<ImageInfo>
  renderJpeg(path: string, dimensions: Dimensions, quality: number): Promise<string>
  getFileSize(path: string): Promise<number>
  persist(path: string): Promise<string>
  remove?(path: string): Promise<void>
}

export interface SourceMetadata {
  capturedAt: string
  orientation: number
}

const ORIENTATION_MAP: Record<string, number> = {
  up: 1,
  'up-mirrored': 2,
  down: 3,
  'down-mirrored': 4,
  'left-mirrored': 5,
  right: 6,
  'right-mirrored': 7,
  left: 8,
}

export function normalizeOrientation(value: string | number | undefined): number {
  if (typeof value === 'number' && value >= 1 && value <= 8) return Math.round(value)
  return ORIENTATION_MAP[String(value || '').toLowerCase()] || 1
}

function exifDateToIso(value: string): string | null {
  const match = value.trim().match(/^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/)
  if (!match) return null
  const [, year, month, day, hour, minute, second] = match
  const parsed = new Date(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), Number(second))
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
}

export function parseJpegExif(buffer: ArrayBuffer): Partial<SourceMetadata> {
  const bytes = new Uint8Array(buffer)
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return {}
  let offset = 2
  while (offset + 4 < bytes.length) {
    if (bytes[offset] !== 0xff) break
    const marker = bytes[offset + 1]
    if (marker === 0xda || marker === 0xd9) break
    const segmentLength = (bytes[offset + 2] << 8) | bytes[offset + 3]
    if (segmentLength < 2 || offset + 2 + segmentLength > bytes.length) break
    if (marker === 0xe1 && bytes[offset + 4] === 0x45 && bytes[offset + 5] === 0x78 && bytes[offset + 6] === 0x69 && bytes[offset + 7] === 0x66) {
      const tiffStart = offset + 10
      const little = bytes[tiffStart] === 0x49 && bytes[tiffStart + 1] === 0x49
      const big = bytes[tiffStart] === 0x4d && bytes[tiffStart + 1] === 0x4d
      if (!little && !big) return {}
      const view = new DataView(buffer)
      const u16 = (position: number) => view.getUint16(position, little)
      const u32 = (position: number) => view.getUint32(position, little)
      const readAscii = (entry: number, count: number): string => {
        const valueOffset = count <= 4 ? entry + 8 : tiffStart + u32(entry + 8)
        if (valueOffset < 0 || valueOffset + count > bytes.length) return ''
        return String.fromCharCode(...bytes.slice(valueOffset, valueOffset + Math.max(0, count - 1)))
      }
      const metadata: Partial<SourceMetadata> = {}
      const firstIfd = tiffStart + u32(tiffStart + 4)
      if (firstIfd + 2 > bytes.length) return metadata
      let exifIfd = 0
      let fallbackDate = ''
      const entries = u16(firstIfd)
      for (let index = 0; index < entries; index += 1) {
        const entry = firstIfd + 2 + index * 12
        if (entry + 12 > bytes.length) break
        const tag = u16(entry)
        const type = u16(entry + 2)
        const count = u32(entry + 4)
        if (tag === 0x0112 && type === 3) metadata.orientation = normalizeOrientation(u16(entry + 8))
        if (tag === 0x8769) exifIfd = tiffStart + u32(entry + 8)
        if (tag === 0x0132 && type === 2) fallbackDate = readAscii(entry, count)
      }
      let originalDate = ''
      let digitizedDate = ''
      if (exifIfd && exifIfd + 2 <= bytes.length) {
        const exifEntries = u16(exifIfd)
        for (let index = 0; index < exifEntries; index += 1) {
          const entry = exifIfd + 2 + index * 12
          if (entry + 12 > bytes.length) break
          const tag = u16(entry)
          const type = u16(entry + 2)
          const count = u32(entry + 4)
          if (type !== 2) continue
          if (tag === 0x9003) originalDate = readAscii(entry, count)
          if (tag === 0x9004) digitizedDate = readAscii(entry, count)
        }
      }
      const capturedAt = exifDateToIso(originalDate) || exifDateToIso(digitizedDate) || exifDateToIso(fallbackDate)
      if (capturedAt) metadata.capturedAt = capturedAt
      return metadata
    }
    offset += 2 + segmentLength
  }
  return {}
}

function getFileModifiedAt(path: string): Promise<string | null> {
  const wxApi = (globalThis as { wx?: any }).wx
  if (!wxApi?.getFileSystemManager) return Promise.resolve(null)
  return new Promise((resolve) => {
    wxApi.getFileSystemManager().stat({
      path,
      success: (result: any) => {
        const value = Number(result?.stats?.lastModifiedTime || result?.stats?.lastAccessedTime || 0)
        resolve(value ? new Date(value).toISOString() : null)
      },
      fail: () => resolve(null),
    })
  })
}

export async function readSourceMetadata(path: string, fallbackCapturedAt = new Date().toISOString()): Promise<Partial<SourceMetadata>> {
  let exif: Partial<SourceMetadata> = {}
  try {
    exif = parseJpegExif(await readFilePrefix(path))
  } catch {
    // Non-JPEG or a platform path that cannot expose raw bytes; use file time below.
  }
  return {
    capturedAt: exif.capturedAt || await getFileModifiedAt(path) || fallbackCapturedAt,
    orientation: exif.orientation,
  }
}

function wxPromise<T>(run: (success: (value: T) => void, fail: (error: unknown) => void) => void): Promise<T> {
  return new Promise((resolve, reject) => run(resolve, reject))
}

function createImageInfo(path: string): Promise<ImageInfo> {
  const wxApi = (globalThis as { wx?: any }).wx
  if (wxApi?.getImageInfo) {
    return wxPromise((success, fail) => wxApi.getImageInfo({ src: path, success, fail })).then((result: any) => ({
      path: result.path || path,
      width: Number(result.width),
      height: Number(result.height),
      orientation: String(result.orientation || 'up'),
      type: String(result.type || ''),
    }))
  }
  return wxPromise((success, fail) => uni.getImageInfo({ src: path, success, fail })).then((result: any) => ({
    path: result.path || path,
    width: Number(result.width),
    height: Number(result.height),
    orientation: String(result.orientation || 'up'),
    type: String(result.type || ''),
  }))
}

function renderWithOffscreenCanvas(path: string, dimensions: Dimensions, quality: number): Promise<string> {
  const wxApi = (globalThis as { wx?: any }).wx
  if (!wxApi?.createOffscreenCanvas || !wxApi?.canvasToTempFilePath) {
    return wxPromise((success, fail) => (uni as any).compressImage({
      src: path,
      quality,
      compressedWidth: dimensions.width,
      compressedHeight: dimensions.height,
      success: (result: { tempFilePath: string }) => success(result.tempFilePath),
      fail,
    }))
  }

  return new Promise((resolve, reject) => {
    try {
      const canvas = wxApi.createOffscreenCanvas({ type: '2d', width: dimensions.width, height: dimensions.height })
      const context = canvas.getContext('2d')
      const image = canvas.createImage()
      image.onload = () => {
        context.clearRect(0, 0, dimensions.width, dimensions.height)
        context.drawImage(image, 0, 0, dimensions.width, dimensions.height)
        wxApi.canvasToTempFilePath({
          canvas,
          fileType: 'jpg',
          quality: quality / 100,
          destWidth: dimensions.width,
          destHeight: dimensions.height,
          success: (result: { tempFilePath: string }) => resolve(result.tempFilePath),
          fail: reject,
        })
      }
      image.onerror = reject
      image.src = path
    } catch (error) {
      reject(error)
    }
  })
}

function getFileSize(path: string): Promise<number> {
  const wxApi = (globalThis as { wx?: any }).wx
  if (wxApi?.getFileSystemManager) {
    return wxPromise((success, fail) => wxApi.getFileSystemManager().getFileInfo({ filePath: path, success, fail }))
      .then((result: any) => Number(result.size))
  }
  return wxPromise((success, fail) => uni.getFileInfo({ filePath: path, success, fail })).then((result: any) => Number(result.size))
}

function persistFile(path: string): Promise<string> {
  const wxApi = (globalThis as { wx?: any }).wx
  if (wxApi?.getFileSystemManager) {
    return wxPromise((success, fail) => wxApi.getFileSystemManager().saveFile({ tempFilePath: path, success, fail }))
      .then((result: any) => String(result.savedFilePath))
  }
  return wxPromise((success, fail) => uni.saveFile({ tempFilePath: path, success, fail })).then((result: any) => String(result.savedFilePath))
}

function removeFile(path: string): Promise<void> {
  const wxApi = (globalThis as { wx?: any }).wx
  if (!wxApi?.getFileSystemManager) return Promise.resolve()
  return new Promise((resolve) => {
    wxApi.getFileSystemManager().unlink({ filePath: path, success: () => resolve(), fail: () => resolve() })
  })
}

export const wechatCompressionAdapter: CompressionAdapter = {
  getImageInfo: createImageInfo,
  renderJpeg: renderWithOffscreenCanvas,
  getFileSize,
  persist: persistFile,
  remove: removeFile,
}

export function getSourceFileSize(sourcePath: string, adapter: CompressionAdapter = wechatCompressionAdapter): Promise<number> {
  return adapter.getFileSize(sourcePath)
}

async function cleanupGeneratedJpegs(paths: Set<string>, keepPath: string, sourcePath: string, adapter: CompressionAdapter): Promise<void> {
  for (const path of paths) {
    if (!path || path === keepPath || path === sourcePath) continue
    try {
      await adapter.remove?.(path)
    } catch {
      // 临时文件清理不能覆盖原始压缩结果或错误。
    }
  }
}

async function bestJpegAtDimensions(
  sourcePath: string,
  dimensions: Dimensions,
  adapter: CompressionAdapter,
  maxBytes = MAX_PREVIEW_BYTES,
): Promise<{ path: string; size: number; quality: number } | null> {
  const generated = new Set<string>()
  let keepPath = ''
  try {
    const minimumPath = await adapter.renderJpeg(sourcePath, dimensions, MIN_JPEG_QUALITY)
    generated.add(minimumPath)
    const minimumSize = await adapter.getFileSize(minimumPath)
    if (!(Number.isFinite(minimumSize) && minimumSize > 0 && minimumSize <= maxBytes)) return null

    let best = { path: minimumPath, size: minimumSize, quality: MIN_JPEG_QUALITY }
    let low = MIN_JPEG_QUALITY + 1
    let high = MAX_JPEG_QUALITY
    while (low <= high) {
      const quality = Math.floor((low + high) / 2)
      const path = await adapter.renderJpeg(sourcePath, dimensions, quality)
      generated.add(path)
      const size = await adapter.getFileSize(path)
      if (Number.isFinite(size) && size > 0 && size <= maxBytes) {
        best = { path, size, quality }
        low = quality + 1
      } else {
        high = quality - 1
      }
    }
    keepPath = best.path
    return best
  } finally {
    await cleanupGeneratedJpegs(generated, keepPath, sourcePath, adapter)
  }
}

function sourceFilename(sourcePath: string): string {
  const cleanPath = sourcePath.replace(/\\/g, '/').split('?')[0]
  return cleanPath.split('/').pop() || `photo-${Date.now()}`
}

function jpegFilename(originalFilename: string): string {
  const filename = sourceFilename(originalFilename)
  const stem = filename.replace(/\.[^.]*$/, '') || `photo-${Date.now()}`
  return `${stem}.jpg`
}

function originalIdentity(originalFilename: string, type = ''): { filename: string; mimeType: SupportedOriginalMimeType } {
  const providedName = sourceFilename(originalFilename)
  const extension = providedName.includes('.') ? providedName.split('.').pop()!.toLowerCase() : ''
  const normalizedType = String(type || '').toLowerCase().replace('image/', '')
  let mimeType: SupportedOriginalMimeType | '' = ''
  if (['jpg', 'jpeg'].includes(normalizedType)) mimeType = 'image/jpeg'
  else if (normalizedType === 'png') mimeType = 'image/png'
  else if (normalizedType) throw new Error(`暂不支持 ${normalizedType.toUpperCase()} 原图，请选择 JPEG 或 PNG`)
  else if (['jpg', 'jpeg'].includes(extension)) mimeType = 'image/jpeg'
  else if (extension === 'png') mimeType = 'image/png'
  if (!mimeType) throw new Error('无法确认原图格式，请选择 JPEG 或 PNG 图片')
  const expectedExtension = mimeType === 'image/png' ? 'png' : 'jpg'
  const filename = providedName && extension ? providedName : `photo-${Date.now()}.${expectedExtension}`
  return { filename, mimeType }
}

export async function inspectOriginalSource(
  originalPath: string,
  originalFilename: string,
  fallbackCapturedAt = new Date().toISOString(),
  adapter: CompressionAdapter = wechatCompressionAdapter,
): Promise<OriginalInspection> {
  const info = await adapter.getImageInfo(originalPath)
  if (!info.width || !info.height) throw new Error('无法读取照片尺寸')
  const identity = originalIdentity(originalFilename, info.type)
  const sourceMetadata = adapter === wechatCompressionAdapter
    ? await readSourceMetadata(originalPath, fallbackCapturedAt)
    : {}
  return {
    originalMimeType: identity.mimeType,
    width: info.width,
    height: info.height,
    orientation: normalizeOrientation(sourceMetadata.orientation || info.orientation),
    capturedAt: sourceMetadata.capturedAt || fallbackCapturedAt,
  }
}

export async function persistOriginalSource(
  sourcePath: string,
  adapter: CompressionAdapter = wechatCompressionAdapter,
): Promise<PersistedOriginal> {
  const originalFilename = sourceFilename(sourcePath)
  const originalPath = await adapter.persist(sourcePath)
  let originalSize = 0
  try {
    originalSize = await adapter.getFileSize(originalPath)
  } catch (error) {
    throw Object.assign(new Error(`原图已保存，但文件大小复核失败：${error instanceof Error ? error.message : '无法读取'}`), { originalPath, originalFilename, originalSize })
  }
  if (!Number.isFinite(originalSize) || originalSize <= 0) {
    throw Object.assign(new Error('原图已保存，但文件大小校验失败'), { originalPath, originalFilename, originalSize })
  }
  return { originalPath, originalSize, originalFilename }
}

export async function prepareTransferImage(
  originalPath: string,
  originalFilename: string,
  adapter: CompressionAdapter = wechatCompressionAdapter,
): Promise<PreparedTransfer> {
  const info = await adapter.getImageInfo(originalPath)
  if (!info.width || !info.height) throw new Error('无法读取照片尺寸')
  let dimensions = fitWithinMaxEdge(info.width, info.height, TRANSFER_INITIAL_MAX_EDGE)
  for (let round = 0; round < 24; round += 1) {
    const candidate = await bestJpegAtDimensions(info.path || originalPath, dimensions, adapter, MAX_TRANSFER_BYTES)
    if (candidate) {
      if (!isTransferWithinLimit(candidate.size)) throw new Error('归档图超过 1MB，已停止上传')
      return {
        transferTempPath: candidate.path,
        transferSize: candidate.size,
        transferWidth: dimensions.width,
        transferHeight: dimensions.height,
        transferFilename: jpegFilename(originalFilename),
      }
    }
    const next = shrinkDimensions(dimensions)
    if (next.width === dimensions.width && next.height === dimensions.height) break
    dimensions = next
  }
  throw new Error('照片内容过于复杂，无法生成 1MB 以内的归档图')
}

export async function persistPreparedTransfer(
  prepared: PreparedTransfer,
  adapter: CompressionAdapter = wechatCompressionAdapter,
): Promise<PersistedTransfer> {
  let transferPath = ''
  try {
    transferPath = await adapter.persist(prepared.transferTempPath)
    const transferSize = await adapter.getFileSize(transferPath)
    if (!isTransferWithinLimit(transferSize)) throw new Error('保存后的归档图超过 1MB，已停止上传')
    return {
      transferPath,
      transferSize,
      transferWidth: prepared.transferWidth,
      transferHeight: prepared.transferHeight,
      transferFilename: prepared.transferFilename,
    }
  } catch (error) {
    if (transferPath) await adapter.remove?.(transferPath)
    throw error
  }
}

export async function preparePreview(
  originalPath: string,
  originalFilename: string,
  fallbackCapturedAt = new Date().toISOString(),
  adapter: CompressionAdapter = wechatCompressionAdapter,
): Promise<PreparedPreview> {
  const info = await adapter.getImageInfo(originalPath)
  if (!info.width || !info.height) throw new Error('无法读取照片尺寸')
  const identity = originalIdentity(originalFilename, info.type)
  const sourceMetadata = adapter === wechatCompressionAdapter
    ? await readSourceMetadata(originalPath, fallbackCapturedAt)
    : {}
  let dimensions = fitWithinMaxEdge(info.width, info.height)

  for (let round = 0; round < 24; round += 1) {
    const candidate = await bestJpegAtDimensions(info.path || originalPath, dimensions, adapter)
    if (candidate) {
      if (candidate.size > MAX_PREVIEW_BYTES) throw new Error('预览图超过 100KB，已停止加入队列')
      return {
        originalMimeType: identity.mimeType,
        previewTempPath: candidate.path,
        previewSize: candidate.size,
        previewWidth: dimensions.width,
        previewHeight: dimensions.height,
        width: info.width,
        height: info.height,
        orientation: normalizeOrientation(sourceMetadata.orientation || info.orientation),
        capturedAt: sourceMetadata.capturedAt || fallbackCapturedAt,
      }
    }
    const next = shrinkDimensions(dimensions)
    if (next.width === dimensions.width && next.height === dimensions.height) break
    dimensions = next
  }
  throw new Error('照片内容过于复杂，无法生成 100KB 以内的本机预览')
}

export async function downloadServerPreview(
  url: string,
  adapter: CompressionAdapter = wechatCompressionAdapter,
): Promise<{ previewPath: string; previewSize: number }> {
  if (!url) throw new Error('服务器没有返回预览地址')
  const tempPath = await wxPromise<string>((success, fail) => uni.downloadFile({
    url,
    timeout: 30_000,
    success: (result) => {
      if (result.statusCode >= 200 && result.statusCode < 300 && result.tempFilePath) success(result.tempFilePath)
      else fail(new Error(`预览下载失败（HTTP ${result.statusCode}）`))
    },
    fail,
  }))
  const downloadedSize = await adapter.getFileSize(tempPath)
  if (!isPreviewWithinLimit(downloadedSize)) throw new Error('服务器预览超过 100KB，已拒绝保存')
  let previewPath = ''
  try {
    previewPath = await adapter.persist(tempPath)
    const previewSize = await adapter.getFileSize(previewPath)
    if (!isPreviewWithinLimit(previewSize)) throw new Error('保存后的服务器预览超过 100KB，已拒绝保留')
    return { previewPath, previewSize }
  } catch (error) {
    if (previewPath) await adapter.remove?.(previewPath)
    throw error
  }
}

export async function persistPreparedPreview(
  prepared: PreparedPreview,
  adapter: CompressionAdapter = wechatCompressionAdapter,
): Promise<PersistedPreview> {
  let previewPath = ''
  try {
    previewPath = await adapter.persist(prepared.previewTempPath)
    const persistedPreviewSize = await adapter.getFileSize(previewPath)
    if (!isPreviewWithinLimit(persistedPreviewSize)) throw new Error('保存后的本机预览超过 100KB，已拒绝加入队列')
    return {
      originalMimeType: prepared.originalMimeType,
      previewPath,
      previewSize: persistedPreviewSize,
      previewWidth: prepared.previewWidth,
      previewHeight: prepared.previewHeight,
      width: prepared.width,
      height: prepared.height,
      orientation: prepared.orientation,
      capturedAt: prepared.capturedAt,
    }
  } catch (error) {
    if (previewPath) await adapter.remove?.(previewPath)
    throw error
  }
}
