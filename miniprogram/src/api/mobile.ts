import { normalizeJoinRequest, type ProjectJoinRequest } from '@/services/project-join-request'
import type { Assignment, BootstrapResponse, CloudPhoto, MatchCandidate, PhotoRequirement, ProjectAccessRole, ProjectInvite, ProjectMember, ProjectNode, ProjectSummary } from '@/types/domain'
import { apiBinaryRequest, apiRequest, apiUploadPhoto } from './client'
import { buildChunkUploadInit, normalizeBatchPayload, type ChunkUploadState, type CreateBatchPayload, type PhotoUploadMetadata } from './contracts'
import { normalizeBatch, normalizeCloudPhoto, normalizeProject, normalizeTreeNode, type NormalizedBatch } from './normalize'
import { normalizeProjectRole } from '@/services/project-membership'

export const CHUNK_FINALIZE_TIMEOUT_MS = 120_000

export interface AuthResponse {
  ok: true
  token?: string
  account?: { id: number | string; username: string; display_name?: string; role?: string }
  binding_required?: boolean
  bootstrap?: BootstrapResponse
  project?: ProjectSummary
  join_request?: ProjectJoinRequest
  pending_approval?: boolean
  already_member?: boolean
}

export interface AccountLoginResponse {
  ok: true
  account: { id: number | string; username: string; display_name?: string; role?: string }
  binding_intent: string
}

function normalizeProjectMember(raw: any): ProjectMember {
  return {
    account_id: String(raw?.account_id ?? raw?.id ?? ''),
    username: String(raw?.username || ''),
    display_name: String(raw?.display_name || raw?.username || '成员'),
    role: normalizeProjectRole(raw?.role || raw?.access_role) || 'viewer',
    joined_at: String(raw?.joined_at || ''),
    is_me: Boolean(raw?.is_me),
  }
}

function normalizeProjectInvite(raw: any): ProjectInvite {
  const invite = raw?.invite && typeof raw.invite === 'object' ? raw.invite : raw
  return {
    code: String(invite?.code || '').toUpperCase(),
    role: normalizeProjectRole(invite?.role) || 'capturer',
    expires_at: String(invite?.expires_at || ''),
    project: normalizeProject(invite?.project),
    inviter_name: String(invite?.inviter_name || ''),
    already_joined: Boolean(invite?.already_joined || raw?.already_joined),
  }
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
  wechatJoin: async (inviteCode: string, displayName: string, phone: string, code: string, appId: string): Promise<AuthResponse> => {
    const raw = await apiRequest<any>('POST', '/auth/wechat-join', { code, app_id: appId, invite_code: inviteCode, display_name: displayName, phone }, false)
    return { ...raw, bootstrap: raw.bootstrap ? normalizeBootstrapResponse(raw.bootstrap) : undefined, project: raw.project ? normalizeProject(raw.project) : undefined, join_request: normalizeJoinRequest(raw.join_request) }
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
    }, true, CHUNK_FINALIZE_TIMEOUT_MS)
  },
  projectMembers: async (projectId: string) => {
    const raw = await apiRequest<any>('GET', `/projects/${encodeURIComponent(projectId)}/members`)
    return {
      ok: true as const,
      project: normalizeProject(raw.project),
      members: Array.isArray(raw.members) ? raw.members.map(normalizeProjectMember) : [],
    }
  },
  createProjectInvite: async (projectId: string, role: ProjectAccessRole) => {
    const raw = await apiRequest<any>('POST', `/projects/${encodeURIComponent(projectId)}/invites`, { role })
    return { ok: true as const, invite: normalizeProjectInvite(raw) }
  },
  previewProjectInvite: async (code: string) => {
    const raw = await apiRequest<any>('POST', '/project-invites/preview', { code })
    const invite = normalizeProjectInvite(raw)
    return { ok: true as const, invite, already_member: Boolean(raw.already_member || raw.already_joined || invite.already_joined) }
  },
  joinProjectInvite: async (code: string, displayName: string, phone: string) => {
    const raw = await apiRequest<any>('POST', '/project-invites/join', { code, display_name: displayName, phone })
    return {
      ok: true as const,
      project: raw.project ? normalizeProject(raw.project) : undefined,
      join_request: normalizeJoinRequest(raw.join_request),
      pending_approval: Boolean(raw.pending_approval),
      already_member: Boolean(raw.already_member),
      membership: raw.membership && typeof raw.membership === 'object' ? raw.membership : undefined,
      bootstrap: raw.bootstrap ? normalizeBootstrapResponse(raw.bootstrap) : undefined,
      idempotent: Boolean(raw.idempotent || raw.already_member),
    }
  },
  listProjectJoinRequests: async () => {
    const raw = await apiRequest<any>('GET', '/project-join-requests')
    return { ok: true as const, requests: (Array.isArray(raw.requests) ? raw.requests : []).map(normalizeJoinRequest).filter((item: ProjectJoinRequest | undefined): item is ProjectJoinRequest => Boolean(item)) as ProjectJoinRequest[] }
  },
  updateProjectMember: async (projectId: string, accountId: string, role: ProjectAccessRole) => {
    const raw = await apiRequest<any>('PATCH', `/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(accountId)}`, { role })
    return {
      ok: true as const,
      project: raw.project ? normalizeProject(raw.project) : undefined,
      member: raw.member ? normalizeProjectMember(raw.member) : undefined,
      members: Array.isArray(raw.members) ? raw.members.map(normalizeProjectMember) : undefined,
    }
  },
  removeProjectMember: async (projectId: string, accountId: string) => {
    const raw = await apiRequest<any>('DELETE', `/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(accountId)}`)
    return { ok: true as const, removed: raw.removed !== false, members: Array.isArray(raw.members) ? raw.members.map(normalizeProjectMember) : undefined }
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
  updateBatchArchiveInfo: async (batchId: string, assignment: Assignment) => {
    const raw = await apiRequest<any>('PATCH', `/batches/${encodeURIComponent(batchId)}/archive-info`, { assignment })
    return { ok: true as const, batch: raw.batch ? normalizeBatch(raw.batch) : undefined }
  },
  commitBatch: async (batchId: string) => {
    const raw = await apiRequest<any>('POST', `/batches/${encodeURIComponent(batchId)}/commit`, {})
    return { ok: true as const, batch: normalizeBatch(raw.batch) }
  },
}
