import type { PhotoUploadMetadata } from './contracts'

function unavailable(): never {
  throw new Error('真实 API 构建不能调用本地样例运行时')
}

export function runtimeRequest<T>(_method: string, _path: string, _data?: unknown): Promise<T> {
  return Promise.reject(unavailable())
}

export function runtimeUpload(
  _batchId: string,
  _metadata: PhotoUploadMetadata,
): Promise<{ ok: true; idempotent?: boolean; photo?: unknown }> {
  return Promise.reject(unavailable())
}
