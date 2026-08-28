import type { CloudPhoto, MatchCandidate, ProjectNode, ProjectSummary } from '@/types/domain'
import { API_BASE_URL } from '@/config/env'

export function normalizeMediaUrl(value: unknown): string {
  const url = String(value || '')
  return url.startsWith('/') ? `${API_BASE_URL}${url}` : url
}

export function normalizeProject(raw: any): ProjectSummary {
  if (!raw || typeof raw !== 'object') throw new Error('服务器工程数据格式不正确')
  const id = String(raw.id || raw.project_id || '')
  const code = String(raw.code || raw.project_code || id)
  const name = String(raw.name || raw.project_name || '')
  if (!id || !name) throw new Error('服务器工程数据缺少编号或名称')
  const metadata = raw.metadata && typeof raw.metadata === 'object' ? raw.metadata : {}
  return {
    id, code, name,
    revision: Number(raw.revision || 0),
    unit_count: Number(raw.unit_count || metadata.unit_count || 0),
    industry: String(raw.industry || metadata.industry || '水利工程'),
    project_type: String(raw.project_type || metadata.project_type || ''),
    region: String(raw.region || metadata.region || ''),
    template_version: String(raw.template_version || metadata.template_version || ''),
    requirement_count: Number(raw.requirement_count || metadata.requirement_count || 0),
  }
}

export function normalizeCandidate(raw: any): MatchCandidate {
  const score = Number(raw?.score || 0)
  return {
    unit_code: String(raw?.unit_code || raw?.project_code || ''),
    unit_name: String(raw?.name || raw?.project_name || ''),
    process_name: String(raw?.process_name || ''),
    other_node_code: String(raw?.other_node_code || ''),
    other_node_name: String(raw?.other_node_name || ''),
    score,
    confidence: Math.max(0, Math.min(1, score > 1 ? score / 1000 : score)),
    reasons: Array.isArray(raw?.reasons) ? raw.reasons.map(String) : [],
    reason: Array.isArray(raw?.reasons) ? raw.reasons.map(String).join('、') : String(raw?.reason || ''),
  }
}

export function normalizeCloudPhoto(raw: any): CloudPhoto {
  if (!raw || typeof raw !== 'object' || !raw.photo_uuid) throw new Error('服务器照片数据格式不正确')
  const assignment = raw.assignment && typeof raw.assignment === 'object' ? raw.assignment : {}
  const downloadUrl = normalizeMediaUrl(raw.download_url)
  const imageUrl = normalizeMediaUrl(raw.image_url) || downloadUrl
  const thumbUrl = normalizeMediaUrl(raw.thumb_url) || downloadUrl
  return {
    photo_uuid: String(raw.photo_uuid),
    title: String(raw.title || '现场工程影像'),
    photo_date: String(raw.photo_date || '').slice(0, 10),
    photographer: String(raw.photographer || ''),
    uploaded_by: String(raw.uploaded_by || ''),
    scope: raw.scope === 'other' ? 'other' : 'engineering',
    category: raw.category === 'supervision' ? 'supervision' : raw.scope === 'other' ? undefined : 'construction',
    unit_code: String(raw.unit_code || assignment.unit_code || ''),
    unit_name: String(raw.unit_name || assignment.unit_name || raw.match?.project_name || ''),
    process_name: String(raw.process_name || assignment.process_name || ''),
    other_node_code: String(raw.other_node_code || assignment.other_node_code || ''),
    other_node_name: String(raw.other_node_name || assignment.other_node_name || ''),
    requirement: raw.requirement?.template_code ? {
      template_code: String(raw.requirement.template_code),
      photo_requirement_name: String(raw.requirement.photo_requirement_name || ''),
    } : undefined,
    download_url: downloadUrl,
    image_url: imageUrl,
    thumb_url: thumbUrl,
    status: raw.status,
    captured_at: String(raw.client_captured_at || raw.captured_at || ''),
    created_at: String(raw.created_at || ''),
  }
}

export function normalizeTreeNode(raw: any): ProjectNode {
  const children = Array.isArray(raw?.children) ? raw.children.map(normalizeTreeNode) : []
  const type = String(raw?.type || raw?.node_type || 'other') as ProjectNode['type']
  const processes = children.filter((child: ProjectNode) => child.type === 'process').map((child: ProjectNode) => child.name)
  return {
    code: String(raw?.code || raw?.node_code || raw?.unit_code || ''),
    name: String(raw?.name || ''),
    type,
    active: raw?.active !== false,
    processes,
    children: children.filter((child: ProjectNode) => child.type !== 'process'),
  }
}

export interface NormalizedBatchPhoto {
  photo_uuid: string
  status: string
  deleted_at?: string
  match_candidates: MatchCandidate[]
  error?: string
  title?: string
  photo_date?: string
}

export interface NormalizedBatch {
  batch_id: string
  client_batch_id?: string
  status: string
  photos: NormalizedBatchPhoto[]
}

export function normalizeBatch(raw: any): NormalizedBatch {
  if (!raw || typeof raw !== 'object' || (raw.batch_id === undefined && raw.id === undefined)) throw new Error('服务器批次数据格式不正确')
  return {
    batch_id: String(raw.batch_id ?? raw.id),
    client_batch_id: raw.client_batch_id ? String(raw.client_batch_id) : undefined,
    status: String(raw.status || ''),
    photos: Array.isArray(raw.photos) ? raw.photos.map((photo: any) => ({
      photo_uuid: String(photo.photo_uuid || ''),
      status: String(photo.status || ''),
      deleted_at: photo.deleted_at ? String(photo.deleted_at) : undefined,
      match_candidates: Array.isArray(photo.match_candidates) ? photo.match_candidates.map(normalizeCandidate) : [],
      error: photo.error?.message ? String(photo.error.message) : undefined,
      title: photo.title ? String(photo.title) : undefined,
      photo_date: photo.photo_date ? String(photo.photo_date).slice(0, 10) : undefined,
    })) : [],
  }
}
