import { API_BASE_URL, API_MODE } from '@/config/env'
import type { ApiErrorShape } from '@/types/domain'
import { runtimeRequest, runtimeUpload } from '@api-runtime'
import { buildPhotoUploadForm, type PhotoUploadMetadata } from './contracts'

const TOKEN_KEY = 'engineering-image:auth-token:v1'
export const DIRECT_UPLOAD_WATCHDOG_MS = 60_000

export class ApiError extends Error {
  code: string
  retryable: boolean
  statusCode?: number

  constructor(message: string, code = 'REQUEST_FAILED', retryable = false, statusCode?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.retryable = retryable
    this.statusCode = statusCode
  }
}

export const tokenStorage = {
  get: () => String(uni.getStorageSync(TOKEN_KEY) || ''),
  set: (token: string) => uni.setStorageSync(TOKEN_KEY, token),
  clear: () => uni.removeStorageSync(TOKEN_KEY),
}

export async function apiRequest<T>(
  method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE',
  path: string,
  data?: unknown,
  requiresAuth = true,
  timeout = 20_000,
): Promise<T> {
  if (API_MODE === 'mock') return runtimeRequest<T>(method, path, data)
  const token = tokenStorage.get()
  return new Promise<T>((resolve, reject) => {
    ;(uni.request as any)({
      url: `${API_BASE_URL}/api/mobile/v1${path}`,
      method,
      data: data as any,
      header: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(requiresAuth && token ? { Authorization: `Bearer ${token}` } : {}),
      },
      timeout,
      success: (response: UniApp.RequestSuccessCallbackResult) => {
        const body = response.data as (T & Partial<ApiErrorShape>) | undefined
        if (response.statusCode >= 200 && response.statusCode < 300 && body) {
          resolve(body)
          return
        }
        reject(new ApiError(body?.error || '服务器请求失败', body?.code || `HTTP_${response.statusCode}`, Boolean(body?.retryable), response.statusCode))
      },
      fail: (error: UniApp.GeneralCallbackResult) => reject(new ApiError(error.errMsg || '网络连接失败', 'NETWORK_ERROR', true)),
    })
  })
}

export async function apiBinaryRequest<T>(path: string, data: ArrayBuffer, headers: Record<string, string>): Promise<T> {
  if (API_MODE === 'mock') return runtimeRequest<T>('PUT', path, { byteLength: data.byteLength, headers })
  const token = tokenStorage.get()
  return new Promise<T>((resolve, reject) => {
    ;(uni.request as any)({
      url: `${API_BASE_URL}/api/mobile/v1${path}`,
      method: 'PUT',
      data,
      header: {
        Accept: 'application/json',
        'Content-Type': 'application/octet-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      timeout: 55_000,
      success: (response: UniApp.RequestSuccessCallbackResult) => {
        const body = response.data as (T & Partial<ApiErrorShape>) | undefined
        if (response.statusCode >= 200 && response.statusCode < 300 && body) resolve(body)
        else reject(new ApiError(body?.error || '照片分片上传失败', body?.code || `HTTP_${response.statusCode}`, Boolean(body?.retryable), response.statusCode))
      },
      fail: (error: UniApp.GeneralCallbackResult) => reject(new ApiError(error.errMsg || '照片分片上传中断', 'UPLOAD_INTERRUPTED', true)),
    })
  })
}

export async function apiUploadPhoto(
  batchId: string,
  filePath: string,
  metadata: PhotoUploadMetadata,
  onProgress?: (progress: number) => void,
): Promise<{ ok: true; idempotent?: boolean; photo?: unknown }> {
  if (API_MODE === 'mock') {
    onProgress?.(45)
    const response = await runtimeUpload(batchId, metadata)
    onProgress?.(100)
    return response
  }
  const token = tokenStorage.get()
  return new Promise((resolve, reject) => {
    let task: ReturnType<typeof uni.uploadFile> | undefined
    let settled = false
    const finish = (action: () => void) => {
      if (settled) return
      settled = true
      clearTimeout(watchdog)
      action()
    }
    const watchdog = setTimeout(() => {
      if (settled) return
      settled = true
      try { task?.abort?.() } catch { /* 超时本身已能释放队列，abort 失败不应覆盖原错误。 */ }
      reject(new ApiError('照片上传超时，1MB 归档图仍保存在本机，请重试', 'UPLOAD_TIMEOUT', true, 408))
    }, DIRECT_UPLOAD_WATCHDOG_MS)
    try {
      task = uni.uploadFile({
        url: `${API_BASE_URL}/api/mobile/v1/batches/${encodeURIComponent(batchId)}/photos`,
        filePath,
        name: 'file',
        formData: buildPhotoUploadForm(metadata),
        header: token ? { Authorization: `Bearer ${token}` } : {},
        timeout: 55_000,
        success: (response) => {
          let body: any
          try {
            body = JSON.parse(response.data)
          } catch {
            finish(() => reject(new ApiError('服务器返回了无法识别的内容', 'INVALID_RESPONSE', true, response.statusCode)))
            return
          }
          if (response.statusCode >= 200 && response.statusCode < 300 && body?.ok) finish(() => resolve(body))
          else finish(() => reject(new ApiError(body?.error || '照片上传失败', body?.code || `HTTP_${response.statusCode}`, Boolean(body?.retryable), response.statusCode)))
        },
        fail: (error) => finish(() => reject(new ApiError(error.errMsg || '照片上传中断', 'UPLOAD_INTERRUPTED', true))),
      })
      task.onProgressUpdate?.((event: { progress: number }) => onProgress?.(Math.max(0, Math.min(100, event.progress))))
    } catch (error) {
      finish(() => reject(new ApiError(error instanceof Error ? error.message : '照片上传无法启动', 'UPLOAD_INTERRUPTED', true)))
    }
  })
}
