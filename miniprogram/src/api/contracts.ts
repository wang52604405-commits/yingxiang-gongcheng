import type { Assignment, CaptureRequirementRef, PhotoCategory, Scope, UploadMode } from '@/types/domain'

export interface CreateBatchPayload {
  client_batch_id: string
  project_id: string
  scope: Scope
  category?: PhotoCategory
  mode: UploadMode
  assignment?: Assignment
  requirement?: CaptureRequirementRef
}

export interface PhotoUploadMetadata {
  photo_uuid: string
  client_captured_at: string
  orientation: number
  width: number
  height: number
  sha256: string
  original_size_bytes: number
  original_filename: string
  original_mime_type: 'image/jpeg' | 'image/png'
  title: string
  photo_date: string
}

export interface ChunkUploadInitPayload extends Omit<PhotoUploadMetadata, 'original_mime_type'> {
  chunk_size_bytes: number
  total_chunks: number
}

export interface ChunkUploadState {
  upload_id: string
  batch_id: string
  photo_uuid: string
  status: string
  total_size_bytes: number
  chunk_size_bytes: number
  total_chunks: number
  uploaded_chunks: number[]
  expires_at?: string
}

export function buildChunkUploadInit(metadata: PhotoUploadMetadata, chunkSizeBytes: number): ChunkUploadInitPayload {
  return {
    photo_uuid: metadata.photo_uuid,
    sha256: metadata.sha256,
    original_size_bytes: metadata.original_size_bytes,
    original_filename: metadata.original_filename,
    client_captured_at: metadata.client_captured_at,
    orientation: metadata.orientation,
    width: metadata.width,
    height: metadata.height,
    title: metadata.title,
    photo_date: metadata.photo_date,
    chunk_size_bytes: chunkSizeBytes,
    total_chunks: Math.ceil(metadata.original_size_bytes / chunkSizeBytes),
  }
}

export function normalizeBatchPayload(payload: CreateBatchPayload): CreateBatchPayload {
  const normalized: CreateBatchPayload = {
    client_batch_id: payload.client_batch_id,
    project_id: payload.project_id,
    scope: payload.scope,
    mode: payload.mode,
  }
  if (payload.scope === 'engineering' && payload.category) normalized.category = payload.category
  if (payload.assignment && Object.values(payload.assignment).some(Boolean)) normalized.assignment = { ...payload.assignment }
  if (payload.scope === 'engineering' && payload.requirement?.template_code) normalized.requirement = { ...payload.requirement }
  return normalized
}

export function buildPhotoUploadForm(metadata: PhotoUploadMetadata): Record<string, string> {
  return {
    photo_uuid: metadata.photo_uuid,
    client_captured_at: metadata.client_captured_at,
    orientation: String(metadata.orientation),
    width: String(metadata.width),
    height: String(metadata.height),
    sha256: metadata.sha256,
    original_size_bytes: String(metadata.original_size_bytes),
    original_filename: metadata.original_filename,
    original_mime_type: metadata.original_mime_type,
    title: metadata.title,
    photo_date: metadata.photo_date,
  }
}

export function batchIdempotencyKey(payload: CreateBatchPayload): string {
  return `batch:${payload.client_batch_id}`
}

export function photoIdempotencyKey(metadata: PhotoUploadMetadata): string {
  return `photo:${metadata.photo_uuid}`
}
