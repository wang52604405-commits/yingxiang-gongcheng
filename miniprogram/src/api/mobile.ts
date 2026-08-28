import type { BootstrapResponse, CloudPhoto, MatchCandidate, PhotoRequirement, ProjectNode, ProjectSummary } from '@/types/domain'
import { apiBinaryRequest, apiRequest, apiUploadPhoto } from './client'
import { buildChunkUploadInit, normalizeBatchPayload, type ChunkUploadState, type CreateBatchPayload, type PhotoUploadMetadata } from './contracts'
import { normalizeBatch, normalizeCloudPhoto, normalizeProject, normalizeTreeNode, type NormalizedBatch } from './normalize'

export interface AuthResponse {
  ok: true
  token?: string
  account?: { id: number | string; username: string; display_name?: string; role?: string }
  binding_required?: boolean
  bootstrap?: BootstrapResponse
}

export interface AccountLoginResponse {
  ok: true
  account: { id: number | string; username: string; display_name?: string; role?: string }
  binding_intent: string
}

export function normalizeBootstrapResponse(raw: any): BootstrapResponse {
  return {
    ok: true,
    account: raw.account,
    server_time: String(raw.server_time || ''),
    current_project: raw.current_project ? normalizeProject(raw.current_project) : null,
    projects: Array.isArray(raw.projects) ? raw.projects.map(normalizeProject) : [],
    queue: raw.queue && typeof raw.queue === 'object' ? raw.queue : {},
    recent_uploads: Array.isArray(raw.recent_uploads) ? raw.recent_uploads.map(normalizeCloudPhoto) : [],
  }
}

function normalizeChunkUpload(raw: any): ChunkUploadState {
  const upload = raw?.upload || raw
  return {
    upload_id: String(upload?.upload_id || ''),
    batch_id: String(upload?.batch_id || ''),
    photo_uuid: String(upload?.photo_uuid || ''),
    status: String(upload?.status || ''),
    total_size_bytes: Number(upload?.total_size_bytes || 0),
    chunk_size_bytes: Number(upload?.chunk_size_bytes || 0),
    total_chunks: Number(upload?.total_chunks || 0),
    uploaded_chunks: Array.isArray(upload?.uploaded_chunks) ? upload.uploaded_chunks.map(Number).filter(Number.isInteger) : [],
    expires_at: upload?.expires_at ? String(upload.expires_at) : undefined,
  }
}

export const mobileApi = {
  accountLogin: (username: string, password: string, code: string, appId: string): Promise<AccountLoginResponse> => {
    return apiRequest<AccountLoginResponse>('POST', '/auth/account-login', {
      username,
      password,
      code,
      app_id: appId,
    }, false)
  },
  wechatLogin: async (code: string, appId: string): Promise<AuthResponse> => {
    const raw = await apiRequest<any>('POST', '/auth/wechat-login', { code, app_id: appId }, false)
    return { ...raw, bootstrap: raw.bootstrap ? normalizeBootstrapResponse(raw.bootstrap) : undefined }
  },
  wechatBindConfirm: async (bindingIntent: string): Promise<AuthResponse> => {
    const raw = await apiRequest<any>('POST', '/auth/wechat-bind-confirm', { binding_intent: bindingIntent }, false)
    return { ...raw, bootstrap: raw.bootstrap ? normalizeBootstrapResponse(raw.bootstrap) : undefined }
  },
  bootstrap: async (): Promise<BootstrapResponse> => {
    const raw = await apiRequest<any>('GET', '/bootstrap')
    return normalizeBootstrapResponse(raw)
  },
  projects: async () => {
    const raw = await apiRequest<any>('GET', '/projects')
    return { ok: true as const, projects: Array.isArray(raw.projects) ? raw.projects.map(normalizeProject) : [] }
  },
  projectRequirements: async (projectId: string, requiredType = '') => {
    const suffix = requiredType ? `?required_type=${encodeURIComponent(requiredType)}` : ''
    const raw = await apiRequest<any>('GET', `/projects/${encodeURIComponent(projectId)}/requirements${suffix}`)
    return {
      ok: true as const,
      project: normalizeProject(raw.project),
      summary: raw.summary || { total: 0, required: 0, conditional: 0, recommended: 0 },
      requirements: (Array.isArray(raw.requirements) ? raw.requirements : []) as PhotoRequirement[],
    }
  },
  projectTree: async (projectId: string) => {
    const raw = await apiRequest<any>('GET', `/projects/${encodeURIComponent(projectId)}/tree`)
    return { ok: true as const, project: normalizeProject(raw.project), nodes: Array.isArray(raw.tree) ? raw.tree.map(normalizeTreeNode) : [], units: Array.isArray(raw.units) ? raw.units : [] }
  },
  otherTree: async (projectId: string) => {
    const raw = await apiRequest<any>('GET', `/projects/${encodeURIComponent(projectId)}/other-tree`)
    return { ok: true as const, project: normalizeProject(raw.project), nodes: Array.isArray(raw.tree) ? raw.tree.map(normalizeTreeNode) : [], units: Array.isArray(raw.units) ? raw.units : [] }
  },
  photos: (query: { project_id: string; scope: string; category?: string; unit_code?: string; other_node_code?: string; cursor?: string; limit?: number }) => {
    const params = Object.entries(query).filter(([, value]) => value !== undefined && value !== '').map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`).join('&')
    return apiRequest<any>('GET', `/photos?${params}`).then((raw) => ({ ok: true as const, photos: Array.isArray(raw.photos) ? raw.photos.map(normalizeCloudPhoto) : [], next_cursor: String(raw.next_cursor || ''), total: Number(raw.total || 0) }))
  },
  photo: (photoUuid: string) => apiRequest<any>('GET', `/photos/${encodeURIComponent(photoUuid)}`).then((raw) => ({ ok: true as const, photo: normalizeCloudPhoto(raw.photo) })),
  createBatch: async (payload: CreateBatchPayload) => {
    const raw = await apiRequest<any>('POST', '/batches', normalizeBatchPayload(payload))
    const batch = normalizeBatch(raw.batch)
    return { ok: true as const, batch_id: batch.batch_id, batch, idempotent: Boolean(raw.idempotent) }
  },
  uploadPhoto: (batchId: string, filePath: string, metadata: PhotoUploadMetadata, onProgress?: (progress: number) => void) => apiUploadPhoto(batchId, filePath, metadata, onProgress),
  initChunkedUpload: async (batchId: string, metadata: PhotoUploadMetadata, chunkSizeBytes: number) => {
    const raw = await apiRequest<any>('POST', `/batches/${encodeURIComponent(batchId)}/chunked-uploads/init`, buildChunkUploadInit(metadata, chunkSizeBytes))
    return { ok: true as const, idempotent: Boolean(raw.idempotent), upload: normalizeChunkUpload(raw) }
  },
  chunkedUpload: async (batchId: string, photoUuid: string) => {
    const raw = await apiRequest<any>('GET', `/batches/${encodeURIComponent(batchId)}/chunked-uploads/${encodeURIComponent(photoUuid)}`)
    return { ok: true as const, upload: normalizeChunkUpload(raw) }
  },
  uploadChunk: async (batchId: string, photoUuid: string, index: number, bytes: ArrayBuffer, sha256: string) => {
    const raw = await apiBinaryRequest<any>(`/batches/${encodeURIComponent(batchId)}/chunked-uploads/${encodeURIComponent(photoUuid)}/chunks/${index}`, bytes, { 'X-Chunk-SHA256': sha256 })
    return { ok: true as const, idempotent: Boolean(raw.idempotent), uploaded_chunks: Array.isArray(raw.uploaded_chunks) ? raw.uploaded_chunks.map(Number) : [index] }
  },
  finalizeChunkedUpload: async (batchId: string, metadata: PhotoUploadMetadata, totalChunks: number) => {
    return apiRequest<any>('POST', `/batches/${encodeURIComponent(batchId)}/chunked-uploads/${encodeURIComponent(metadata.photo_uuid)}/finalize`, {
      sha256: metadata.sha256,
      original_size_bytes: metadata.original_size_bytes,
      total_chunks: totalChunks,
    })
  },
  batch: async (batchId: string): Promise<{ ok: true; batch_id: string; status: string; photos: NormalizedBatch['photos'] }> => {
    const raw = await apiRequest<any>('GET', `/batches/${encodeURIComponent(batchId)}`)
    const batch = normalizeBatch(raw.batch)
    return { ok: true, batch_id: batch.batch_id, status: batch.status, photos: batch.photos }
  },
  analyzeBatch: async (batchId: string) => {
    const raw = await apiRequest<any>('POST', `/batches/${encodeURIComponent(batchId)}/analyze`, {})
    return {
      ok: true as const,
      idempotent: Boolean(raw.idempotent),
      job: raw.job ? { job_id: String(raw.job.job_id || ''), status: String(raw.job.status || '') } : undefined,
      batch: raw.batch ? normalizeBatch(raw.batch) : undefined,
    }
  },
  assignBatch: async (batchId: string, assignments: Array<Record<string, unknown>>) => {
    const raw = await apiRequest<any>('PATCH', `/batches/${encodeURIComponent(batchId)}/assignments`, { assignments })
    return { ok: true as const, batch: normalizeBatch(raw.batch) }
  },
  commitBatch: async (batchId: string) => {
    const raw = await apiRequest<any>('POST', `/batches/${encodeURIComponent(batchId)}/commit`, {})
    return { ok: true as const, batch: normalizeBatch(raw.batch) }
  },
}
