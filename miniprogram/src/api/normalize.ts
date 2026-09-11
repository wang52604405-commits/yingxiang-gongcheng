import type { CloudPhoto, MatchCandidate, ProjectNode, ProjectSummary } from '@/types/domain'
import { API_BASE_URL } from '@/config/env'
import { normalizeProjectRole } from '@/services/project-membership'

function optionalBoolean(...values: unknown[]): boolean | undefined {
  const value = values.find((item) => typeof item === 'boolean')
  return typeof value === 'boolean' ? value : undefined
}

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
  const membership = raw.membership && typeof raw.membership === 'object' ? raw.membership : {}
  const permissions = membership.permissions && typeof membership.permissions === 'object' ? membership.permissions : {}
  return {
    id, code, name,
    photographer_name: String(raw.photographer_name || ''),
    photographer_verified: raw.photographer_verified === true,
    owner_account_id: String(raw.owner_account_id || membership.owner_account_id || ''),
    local_project_id: String(raw.local_project_id || raw.source_project_id || ''),
    access_role: normalizeProjectRole(raw.access_role || membership.role),
    member_count: Math.max(0, Number(raw.member_count ?? membership.member_count ?? 0)),
    upload_allowed: optionalBoolean(raw.upload_allowed),
    membership_active: optionalBoolean(raw.membership_active, raw.upload_quota?.unlimited),
    upload_quota: raw.upload_quota && typeof raw.upload_quota === 'object' ? raw.upload_quota : undefined,
    can_capture: optionalBoolean(raw.can_capture, membership.can_capture, permissions.can_capture),
    can_manage_members: optionalBoolean(raw.can_manage_members, membership.can_manage_members, permissions.can_manage_members),
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
  const project = raw.project && typeof raw.project === 'object' ? raw.project : {}
  const match = raw.match && typeof raw.match === 'object' ? raw.match : {}
  const matchedHierarchy = Array.isArray(match.candidates)
    ? match.candidates.find((candidate: any) => String(candidate?.unit_code || candidate?.project_code || '') === String(raw.unit_code || assignment.unit_code || match.unit_code || '')) || {}
    : {}
  const downloadUrl = normalizeMediaUrl(raw.download_url)
  const imageUrl = normalizeMediaUrl(raw.image_url) || downloadUrl
  const thumbUrl = normalizeMediaUrl(raw.thumb_url) || downloadUrl
  return {
    photo_uuid: String(raw.photo_uuid),
    project_id: String(raw.project_ref || raw.project_id || project.id || project.project_id || ''),
    project_name: String(raw.project_name || project.name || project.project_name || ''),
    title: String(raw.title || '现场工程影像'),
    photo_date: String(raw.photo_date || '').slice(0, 10),
    photographer: String(raw.photographer || ''),
    uploaded_by: String(raw.uploaded_by || ''),
    photographer_account_id: String(raw.photographer_account_id || ''),
    uploaded_by_account_id: String(raw.uploaded_by_account_id || ''),
    capture_source: raw.capture_source === 'album' ? 'album' : raw.capture_source === 'camera' ? 'camera' : undefined,
    scope: raw.scope === 'other' ? 'other' : 'engineering',
    category: raw.category === 'supervision' ? 'supervision' : raw.scope === 'other' ? undefined : 'construction',
    unit_project_code: String(raw.unit_project_code || assignment.unit_project_code || matchedHierarchy.unit_project_code || ''),
    unit_project_name: String(raw.unit_project_name || assignment.unit_project_name || matchedHierarchy.unit_project_name || ''),
    part_code: String(raw.part_code || assignment.part_code || matchedHierarchy.part_code || ''),
    part_name: String(raw.part_name || assignment.part_name || matchedHierarchy.part_name || ''),
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
  const explicitProcesses = Array.isArray(raw?.processes) ? raw.processes.filter((value: unknown): value is string => typeof value === 'string') : []
  const childProcesses = children.filter((child: ProjectNode) => child.type === 'process' && child.active !== false).map((child: ProjectNode) => child.name)
  const processes = [...new Set<string>([...explicitProcesses, ...childProcesses].map((name: string) => name.trim()).filter(Boolean))]
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
  review_reason?: string
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
      review_reason: photo.review_reason ? String(photo.review_reason) : undefined,
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
