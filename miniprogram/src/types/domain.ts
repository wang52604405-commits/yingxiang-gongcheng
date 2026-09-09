export type Scope = 'engineering' | 'other'
export type PhotoCategory = 'construction' | 'supervision'
export type UploadMode = 'direct' | 'auto'
export type PhotoCaptureSource = 'camera' | 'album'
export type TransferProfile = 'jpeg_1m'
export type ProjectAccessRole = 'owner' | 'admin' | 'capturer' | 'viewer'

export type PhotoStatus =
  | 'local_ready'
  | 'uploading'
  | 'server_saved'
  | 'analyzing'
  | 'needs_review'
  | 'desktop_pending'
  | 'desktop_imported'
  | 'local_deleted'
  | 'failed'

export interface Account {
  id: number | string
  username: string
  display_name?: string
  role?: string
}

export interface ProjectSummary {
  id: string
  code: string
  name: string
  owner_account_id?: string
  local_project_id?: string
  access_role?: ProjectAccessRole
  member_count?: number
  can_capture?: boolean
  can_manage_members?: boolean
  revision?: number
  unit_count?: number
  industry?: string
  project_type?: string
  region?: string
  template_version?: string
  requirement_count?: number
}

export interface ProjectMember {
  account_id: string
  username: string
  display_name: string
  role: ProjectAccessRole
  joined_at?: string
  is_me?: boolean
}

export interface ProjectInvite {
  code: string
  role: ProjectAccessRole
  expires_at?: string
  project: ProjectSummary
  inviter_name?: string
  already_joined?: boolean
}

export interface PhotoRequirement {
  template_code: string
  industry: string
  project_type: string
  phase: string
  division: string
  subdivision?: string
  item?: string
  process?: string
  photo_requirement_name: string
  required_type: 'required' | 'conditional' | 'recommended'
  condition?: string
  min_photo_count: number
  recommended_photo_count: number
  shot_types?: string
  timing?: string
  before_concealment_required?: string
  gps_required?: string
  exif_required?: string
  description_template?: string
  standard_source?: string
  template_version?: string
}

export interface CaptureRequirementRef {
  template_code: string
  photo_requirement_name: string
  required_type?: PhotoRequirement['required_type']
  min_photo_count?: number
  timing?: string
  shot_types?: string
}

export interface ProjectNode {
  code: string
  name: string
  type: 'contract' | 'unit_project' | 'part' | 'unit' | 'process' | 'other'
  active?: boolean
  processes?: string[]
  children?: ProjectNode[]
}

export interface Assignment {
  unit_project_code?: string
  unit_project_name?: string
  part_code?: string
  part_name?: string
  unit_code?: string
  unit_name?: string
  process_name?: string
  process_required?: boolean
  other_node_code?: string
  other_node_name?: string
}

export interface UploadDraft {
  assignment_explicit?: boolean
  capture_item_id?: string
  title?: string
  photographer?: string
  photo_date?: string
  project_id: string
  project_name?: string
  scope: Scope
  category?: PhotoCategory
  mode: UploadMode
  capture_source?: PhotoCaptureSource
  transfer_profile?: TransferProfile
  assignment?: Assignment
  requirement?: CaptureRequirementRef
}

export interface LocalPhoto {
  owner_account_id: string
  photo_uuid: string
  client_batch_id: string
  remote_batch_id?: string
  original_path: string
  original_size: number
  original_sha256: string
  original_filename: string
  original_mime_type: 'image/jpeg' | 'image/png' | ''
  transfer_path?: string
  transfer_size?: number
  transfer_sha256?: string
  transfer_filename?: string
  transfer_width?: number
  transfer_height?: number
  preview_path: string
  preview_size: number
  preview_sha256: string
  preview_width: number
  preview_height: number
  width: number
  height: number
  orientation: number
  client_captured_at: string
  title: string
  photo_date: string
  draft: UploadDraft
  status: PhotoStatus
  retry_from?: PhotoStatus
  progress: number
  error?: string
  failure_code?: string
  retryable?: boolean
  auto_retry_pending?: boolean
  auto_retry_attempts?: number
  next_retry_at?: string
  match_candidates?: MatchCandidate[]
  created_at: string
  updated_at: string
  original_removed?: boolean
  server_saved_at?: string
  deleted_at?: string
  local_deleted_at?: string
  preparation_pending?: boolean
  preview_recovery_pending?: boolean
  preview_error?: string
  preview_retry_attempts?: number
  preview_next_retry_at?: string
  upload_mode?: 'direct' | 'chunked'
  upload_chunk_size?: number
  upload_total_chunks?: number
  uploaded_chunks?: number[]
  chunk_upload_id?: string
}

export interface LocalBatch {
  owner_account_id: string
  client_batch_id: string
  remote_batch_id?: string
  draft: UploadDraft
  archive_info_sync_pending?: boolean
  archive_info_sync_error?: string
  archive_info_sync_failure_code?: string
  archive_info_sync_retryable?: boolean
  photo_uuids: string[]
  committed: boolean
  analyzed: boolean
  analysis_requested?: boolean
  analysis_job_id?: string
  created_at: string
  preparation_error?: string
}

export interface MatchCandidate {
  unit_code?: string
  unit_name?: string
  process_name?: string
  other_node_code?: string
  other_node_name?: string
  confidence: number
  score?: number
  reasons?: string[]
  reason?: string
}

export interface CloudPhoto {
  photo_uuid: string
  title: string
  photo_date: string
  project_id?: string
  project_name?: string
  photographer?: string
  uploaded_by?: string
  photographer_account_id?: string
  uploaded_by_account_id?: string
  capture_source?: PhotoCaptureSource
  scope: Scope
  category?: PhotoCategory
  unit_project_code?: string
  unit_project_name?: string
  part_code?: string
  part_name?: string
  unit_code?: string
  unit_name?: string
  process_name?: string
  other_node_code?: string
  other_node_name?: string
  requirement?: CaptureRequirementRef
  image_url?: string
  thumb_url?: string
  download_url?: string
  status: PhotoStatus
  captured_at?: string
  created_at?: string
}

export interface BootstrapResponse {
  ok: true
  account: Account
  server_time: string
  current_project: ProjectSummary | null
  projects: ProjectSummary[]
  queue: Record<string, number>
  recent_uploads: CloudPhoto[]
}

export interface ApiErrorShape {
  ok?: false
  code: string
  error: string
  retryable?: boolean
}
