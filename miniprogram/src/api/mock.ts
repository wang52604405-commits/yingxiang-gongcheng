import { CURRENT_PROJECT } from '@/config/env'
import type { BootstrapResponse, CloudPhoto, MatchCandidate, PhotoRequirement, ProjectMember, ProjectNode, ProjectSummary } from '@/types/domain'
import type { CreateBatchPayload, PhotoUploadMetadata } from './contracts'

interface MockBatch {
  id: string
  payload: CreateBatchPayload
  photos: Map<string, { metadata: PhotoUploadMetadata; status: string; match_candidates?: MatchCandidate[] }>
  committed: boolean
}

const projects: ProjectSummary[] = [{ ...CURRENT_PROJECT, id: 'mock-account:default', owner_account_id: 'mock-account', local_project_id: 'default', access_role: 'owner', member_count: 2, can_capture: true, can_manage_members: true, revision: 1, unit_count: 888 }]
const rawProject = (project: ProjectSummary) => ({
  id: project.id, project_id: project.id, project_ref: project.id, local_project_id: project.local_project_id,
  owner_account_id: project.owner_account_id, project_code: project.code, project_name: project.name,
  access_role: project.access_role, member_count: project.member_count, can_capture: project.can_capture,
  can_manage_members: project.can_manage_members, revision: project.revision || 0, metadata: { unit_count: project.unit_count || 0 },
})
const batches = new Map<string, MockBatch>()
const batchByClientId = new Map<string, string>()
const chunkUploads = new Map<string, { metadata: PhotoUploadMetadata; chunkSize: number; totalChunks: number; uploaded: Set<number>; status: string }>()
let mockMembers: ProjectMember[] = [
  { account_id: 'mock-account', username: '体验账号', display_name: '工程资料员', role: 'owner', is_me: true },
  { account_id: 'mock-capturer', username: 'collector', display_name: '现场采集员', role: 'capturer' },
]

const engineeringTree: ProjectNode[] = [
  {
    code: 'YNLQ',
    name: CURRENT_PROJECT.name,
    type: 'contract',
    children: [
      {
        code: 'YNLQ-DW-001',
        name: '洺河龙泉缓洪工程',
        type: 'unit_project',
        children: [
          {
            code: 'YNLQ-FB-001',
            name: '拦河闸工程',
            type: 'part',
            children: [
              { code: 'YNLQ-DY-001', name: '拦河闸进口段', type: 'unit', processes: ['基础清理', '钢筋安装', '模板安装', '混凝土浇筑', '成品外观'] },
              { code: 'YNLQ-DY-002', name: '拦河闸闸室段', type: 'unit', processes: ['钢筋验收', '模板验收', '混凝土浇筑'] },
              { code: 'YNLQ-DY-003', name: '拦河闸连接堤', type: 'unit', processes: ['土方填筑', '碾压检测', '成品外观'] },
            ],
          },
        ],
      },
    ],
  },
]

const otherTree: ProjectNode[] = [
  {
    code: 'YNLQ-QT-001',
    name: '临建工程影像',
    type: 'other',
    children: [
      { code: 'YNLQ-QT-001-01', name: '临时道路', type: 'other' },
      { code: 'YNLQ-QT-001-02', name: '施工营地', type: 'other' },
    ],
  },
]

const samplePhotos: CloudPhoto[] = [
  { photo_uuid: 'demo-1', title: '钢筋安装检查', photo_date: '2026-08-25', photographer: '现场采集员', uploaded_by: '现场采集员', photographer_account_id: 'mock-capturer', uploaded_by_account_id: 'mock-capturer', capture_source: 'camera', scope: 'engineering', category: 'construction', unit_code: 'YNLQ-DY-001', unit_name: '拦河闸进口段', process_name: '钢筋安装', status: 'desktop_imported', created_at: '2026-08-25T01:28:00Z' },
  { photo_uuid: 'demo-2', title: '模板验收', photo_date: '2026-08-25', scope: 'engineering', category: 'supervision', unit_code: 'YNLQ-DY-002', unit_name: '拦河闸闸室段', process_name: '模板验收', status: 'desktop_imported', created_at: '2026-08-25T00:56:00Z' },
  { photo_uuid: 'demo-3', title: '土方碾压', photo_date: '2026-08-24', scope: 'engineering', category: 'construction', unit_code: 'YNLQ-DY-003', unit_name: '拦河闸连接堤', process_name: '碾压检测', status: 'desktop_pending', created_at: '2026-08-24T09:10:00Z' },
  { photo_uuid: 'demo-4', title: '临时道路巡查', photo_date: '2026-08-24', scope: 'other', other_node_code: 'YNLQ-QT-001-01', other_node_name: '临时道路', status: 'desktop_imported', created_at: '2026-08-24T08:10:00Z' },
]

const sampleRequirements: PhotoRequirement[] = [
  {
    template_code: 'SL-JZ-001', industry: '水利工程', project_type: '水闸工程', phase: '施工阶段', division: '拦河闸工程', subdivision: '进口段', process: '钢筋安装',
    photo_requirement_name: '钢筋安装隐蔽验收', required_type: 'required', min_photo_count: 3, recommended_photo_count: 5,
    shot_types: '全景、中景、节点近景', timing: '钢筋安装完成、隐蔽验收前', before_concealment_required: '是', exif_required: '是', template_version: 'V1.2',
  },
  {
    template_code: 'SL-JZ-002', industry: '水利工程', project_type: '水闸工程', phase: '施工阶段', division: '拦河闸工程', subdivision: '闸室段', process: '模板安装',
    photo_requirement_name: '模板尺寸与加固检查', required_type: 'conditional', condition: '采用现浇混凝土时', min_photo_count: 2, recommended_photo_count: 4,
    shot_types: '全景、尺量近景', timing: '混凝土浇筑前', before_concealment_required: '是', exif_required: '是', template_version: 'V1.2',
  },
  {
    template_code: 'SL-TF-001', industry: '水利工程', project_type: '堤防工程', phase: '施工阶段', division: '连接堤工程', process: '土方碾压',
    photo_requirement_name: '分层铺土与碾压过程', required_type: 'recommended', min_photo_count: 2, recommended_photo_count: 3,
    shot_types: '作业面全景、碾压设备中景', timing: '每个代表性作业面施工时', gps_required: '是', exif_required: '是', template_version: 'V1.2',
  },
]

let mockJoinRequest: Record<string, unknown> | null = null
const mockAccount = { id: 'mock-account', username: '体验账号', display_name: '工程资料员', role: '资料员' }
let mockActiveAccount = mockAccount
const mockReviewRequests: Record<string, unknown>[] = [{ id: 'mock-review-request', status: 'pending', project_id: projects[0].id, project_name: projects[0].name, display_name: '王建国（示例）', phone: '13800000000', applicant_account_id: 'mock-review-applicant', approver_account_id: mockAccount.id, role: 'capturer', created_at: '2026-09-09T09:30:00' }]

function mockVisibleProjects(): ProjectSummary[] {
  if (mockActiveAccount.id === mockAccount.id) return projects
  if (mockJoinRequest?.status !== 'approved') return []
  if (!mockMembers.some((member) => member.account_id === mockActiveAccount.id)) return []
  return projects.map((project) => ({ ...project, access_role: 'capturer', can_manage_members: false }))
}

function canReviewMock(row: Record<string, unknown>): boolean {
  return row.applicant_account_id !== mockActiveAccount.id && row.approver_account_id === mockActiveAccount.id
}

function mockBootstrap(): BootstrapResponse {
  const available = mockVisibleProjects()
  return {
    ok: true,
    account: mockActiveAccount,
    server_time: new Date().toISOString(),
    current_project: (available[0] ? rawProject(available[0]) : null) as any,
    projects: available.map(rawProject) as any,
    queue: { desktop_pending: 1 },
    recent_uploads: available.length ? samplePhotos.slice(0, 3) : [],
  }
}

export async function mockRequest<T>(method: string, path: string, data?: unknown): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, 80))
  if (path === '/auth/wechat-join' && method === 'POST') {
    const input = data as { invite_code?: string; display_name?: string; phone?: string }
    if (!/^[A-Z0-9]{10}$/.test(input?.invite_code || '') || !input?.display_name?.trim() || !/^1[3-9]\d{9}$/.test(input?.phone || '')) throw new Error('请填写完整邀请码、姓名和手机号')
    const account = { id: 'mock-applicant', username: '微信申请人', display_name: input.display_name.trim(), role: 'member' }
    mockActiveAccount = account
    mockJoinRequest = { id: 'mock-request', status: 'pending', project_id: projects[0].id, project_name: projects[0].name, display_name: account.display_name, phone: input.phone, applicant_account_id: account.id, approver_account_id: 'mock-account', role: 'capturer', can_review: false, created_at: new Date().toISOString() }
    return { ok: true, token: 'mock-member-token', account, bootstrap: { ...mockBootstrap(), account, projects: [], current_project: null, recent_uploads: [], queue: {} }, join_request: mockJoinRequest, pending_approval: true } as T
  }
  if (/^\/project-join-requests(?:\?|$)/.test(path) && method === 'GET') {
    const projectId = new URLSearchParams(path.split('?')[1] || '').get('project_id')
    const rows = [...mockReviewRequests, ...(mockJoinRequest ? [mockJoinRequest] : [])]
      .filter((row) => (!projectId || row.project_id === projectId) && (row.applicant_account_id === mockActiveAccount.id || canReviewMock(row)))
      .map((row) => ({ ...row, can_review: canReviewMock(row) }))
    return { ok: true, requests: rows } as T
  }
  const reviewMatch = path.match(/^\/project-join-requests\/([^/]+)\/(approve|reject)$/)
  if (reviewMatch && method === 'POST') {
    const row = [...mockReviewRequests, ...(mockJoinRequest ? [mockJoinRequest] : [])].find((item) => item.id === decodeURIComponent(reviewMatch[1]))
    if (!row || !canReviewMock(row)) throw new Error('无审核权限')
    if (row.status !== 'pending') throw new Error('该申请已处理')
    row.status = reviewMatch[2] === 'approve' ? 'approved' : 'rejected'
    if (row.status === 'approved' && !mockMembers.some((member) => member.account_id === row.applicant_account_id)) mockMembers.push({ account_id: String(row.applicant_account_id), username: 'wx_mock-member', display_name: String(row.display_name), role: 'capturer' })
    projects[0].member_count = mockMembers.length
    return { ok: true, join_request: { ...row, can_review: false } } as T
  }
  if (path === '/auth/account-login' && method === 'POST') {
    return { ok: true, account: mockAccount, binding_intent: 'mock-binding-intent' } as T
  }
  if (path === '/auth/wechat-login' && method === 'POST') {
    mockActiveAccount = mockAccount
    return { ok: true, token: 'mock-token', account: mockAccount, bootstrap: mockBootstrap() } as T
  }
  if (path === '/auth/wechat-bind-confirm' && method === 'POST') {
    mockActiveAccount = mockAccount
    return { ok: true, token: 'mock-token', account: mockAccount, bootstrap: mockBootstrap() } as T
  }
  if (path === '/bootstrap' && method === 'GET') {
    return mockBootstrap() as T
  }
  if (path === '/projects' && method === 'GET') return { ok: true, projects: mockVisibleProjects().map(rawProject) } as T
  const memberListMatch = path.match(/^\/projects\/([^/]+)\/members$/)
  if (memberListMatch && method === 'GET') return { ok: true, project: rawProject(projects[0]), members: mockMembers } as T
  const createInviteMatch = path.match(/^\/projects\/([^/]+)\/invites$/)
  if (createInviteMatch && method === 'POST') {
    const role = String((data as any)?.role || 'capturer')
    return { ok: true, invite: { invite_id: 'mock-invite', code: 'TEAM123456', role, expires_at: '2026-08-30T00:00:00Z', project: rawProject(projects[0]), inviter_name: '工程资料员' } } as T
  }
  if (path === '/project-invites/preview' && method === 'POST') {
    return { ok: true, invite: { invite_id: 'mock-invite', code: String((data as any)?.code || 'TEAM123456'), role: 'capturer', expires_at: '2026-08-30T00:00:00Z', project: rawProject(projects[0]), inviter_name: '工程资料员' } } as T
  }
  if (path === '/project-invites/join' && method === 'POST') {
    const input = data as { code?: string; display_name?: string; phone?: string }
    if (!input.display_name?.trim() || !/^1[3-9]\d{9}$/.test(input.phone || '')) throw new Error('请填写姓名和手机号')
    mockJoinRequest = { id: 'mock-request', status: 'pending', project_id: projects[0].id, project_name: projects[0].name, display_name: input.display_name.trim(), phone: input.phone, applicant_account_id: mockAccount.id, approver_account_id: 'mock-owner', role: 'capturer', can_review: false, created_at: new Date().toISOString() }
    return { ok: true, join_request: mockJoinRequest, pending_approval: true } as T
  }
  const memberMutationMatch = path.match(/^\/projects\/([^/]+)\/members\/([^/]+)$/)
  if (memberMutationMatch && method === 'PATCH') {
    mockMembers = mockMembers.map((member) => member.account_id === decodeURIComponent(memberMutationMatch[2]) ? { ...member, role: (data as any)?.role || member.role } : member)
    return { ok: true, member: mockMembers.find((member) => member.account_id === decodeURIComponent(memberMutationMatch[2])), members: mockMembers } as T
  }
  if (memberMutationMatch && method === 'DELETE') {
    mockMembers = mockMembers.filter((member) => member.account_id !== decodeURIComponent(memberMutationMatch[2]))
    projects[0].member_count = mockMembers.length
    return { ok: true, removed: true, members: mockMembers } as T
  }
  const requirementsMatch = path.match(/^\/projects\/([^/?]+)\/requirements(?:\?(.*))?$/)
  if (requirementsMatch && method === 'GET') {
    const requiredType = new URLSearchParams(requirementsMatch[2] || '').get('required_type')
    const requirements = requiredType ? sampleRequirements.filter((item) => item.required_type === requiredType) : sampleRequirements
    const summary = sampleRequirements.reduce((result, item) => {
      result.total += 1
      result[item.required_type] += 1
      return result
    }, { total: 0, required: 0, conditional: 0, recommended: 0 })
    return { ok: true, project: { ...rawProject(projects[0]), industry: '水利工程', project_type: '水闸工程', requirement_count: sampleRequirements.length }, summary, requirements } as T
  }
  if (path.endsWith('/tree') && !path.endsWith('/other-tree') && method === 'GET') return { ok: true, project: rawProject(projects[0]), tree: engineeringTree, units: [] } as T
  if (path.endsWith('/other-tree') && method === 'GET') return { ok: true, project: rawProject(projects[0]), tree: otherTree, units: [] } as T
  if (path.startsWith('/photos?') && method === 'GET') {
    const query = decodeURIComponent(path.split('?')[1] || '')
    const scope = query.includes('scope=other') ? 'other' : 'engineering'
    const category = query.includes('category=supervision') ? 'supervision' : 'construction'
    const photos = samplePhotos.filter((photo) => photo.scope === scope && (scope === 'other' || photo.category === category))
    return { ok: true, photos, total: photos.length, next_cursor: null } as T
  }
  if (path.startsWith('/photos/') && method === 'GET') {
    return { ok: true, photo: samplePhotos.find((photo) => photo.photo_uuid === path.split('/').pop()) || samplePhotos[0] } as T
  }
  if (path === '/batches' && method === 'POST') {
    const payload = data as CreateBatchPayload
    const existingId = batchByClientId.get(payload.client_batch_id)
    if (existingId) {
      const existing = batches.get(existingId)!
      return { ok: true, idempotent: true, batch: { batch_id: existingId, client_batch_id: existing.payload.client_batch_id, status: 'local_ready', photos: [...existing.photos.entries()].map(([photo_uuid, photo]) => ({ photo_uuid, ...photo })) } } as T
    }
    const id = `mock-${payload.client_batch_id}`
    batches.set(id, { id, payload, photos: new Map(), committed: false })
    batchByClientId.set(payload.client_batch_id, id)
    return { ok: true, idempotent: false, batch: { batch_id: id, client_batch_id: payload.client_batch_id, status: 'local_ready', photos: [] } } as T
  }
  const batchMatch = path.match(/^\/batches\/([^/]+)$/)
  if (batchMatch && method === 'GET') {
    const batch = batches.get(batchMatch[1])
    return { ok: true, batch: { batch_id: batch?.id, client_batch_id: batch?.payload.client_batch_id, status: batch?.committed ? 'desktop_pending' : 'local_ready', photos: batch ? [...batch.photos.entries()].map(([photo_uuid, photo]) => ({ photo_uuid, ...photo, status: batch.committed ? 'desktop_pending' : photo.status })) : [] } } as T
  }
  const chunkInitMatch = path.match(/^\/batches\/([^/]+)\/chunked-uploads\/init$/)
  if (chunkInitMatch && method === 'POST') {
    const payload = data as PhotoUploadMetadata & { chunk_size_bytes: number; total_chunks: number }
    const key = `${chunkInitMatch[1]}:${payload.photo_uuid}`
    if (!chunkUploads.has(key)) chunkUploads.set(key, { metadata: payload, chunkSize: payload.chunk_size_bytes, totalChunks: payload.total_chunks, uploaded: new Set(), status: 'uploading' })
    const upload = chunkUploads.get(key)!
    return { ok: true, idempotent: upload.uploaded.size > 0, upload: {
      upload_id: `mock-upload-${payload.photo_uuid}`, batch_id: chunkInitMatch[1], photo_uuid: payload.photo_uuid, status: upload.status,
      total_size_bytes: payload.original_size_bytes, chunk_size_bytes: upload.chunkSize, total_chunks: upload.totalChunks, uploaded_chunks: [...upload.uploaded],
    } } as T
  }
  const chunkStateMatch = path.match(/^\/batches\/([^/]+)\/chunked-uploads\/([^/]+)$/)
  if (chunkStateMatch && method === 'GET') {
    const key = `${chunkStateMatch[1]}:${chunkStateMatch[2]}`
    const upload = chunkUploads.get(key)
    if (!upload) throw Object.assign(new Error('Mock 分片会话不存在'), { code: 'UPLOAD_NOT_FOUND', retryable: true })
    return { ok: true, upload: {
      upload_id: `mock-upload-${chunkStateMatch[2]}`, batch_id: chunkStateMatch[1], photo_uuid: chunkStateMatch[2], status: upload.status,
      total_size_bytes: upload.metadata.original_size_bytes, chunk_size_bytes: upload.chunkSize, total_chunks: upload.totalChunks, uploaded_chunks: [...upload.uploaded],
    } } as T
  }
  const chunkPartMatch = path.match(/^\/batches\/([^/]+)\/chunked-uploads\/([^/]+)\/chunks\/(\d+)$/)
  if (chunkPartMatch && method === 'PUT') {
    const upload = chunkUploads.get(`${chunkPartMatch[1]}:${chunkPartMatch[2]}`)
    if (!upload) throw Object.assign(new Error('Mock 分片会话不存在'), { code: 'UPLOAD_NOT_FOUND', retryable: true })
    const index = Number(chunkPartMatch[3])
    const idempotent = upload.uploaded.has(index)
    upload.uploaded.add(index)
    return { ok: true, idempotent, upload_id: `mock-upload-${chunkPartMatch[2]}`, photo_uuid: chunkPartMatch[2], chunk_index: index, uploaded_chunks: [...upload.uploaded] } as T
  }
  const chunkFinalizeMatch = path.match(/^\/batches\/([^/]+)\/chunked-uploads\/([^/]+)\/finalize$/)
  if (chunkFinalizeMatch && method === 'POST') {
    const key = `${chunkFinalizeMatch[1]}:${chunkFinalizeMatch[2]}`
    const upload = chunkUploads.get(key)
    const batch = batches.get(chunkFinalizeMatch[1])
    if (!upload || !batch) throw Object.assign(new Error('Mock 分片会话不存在'), { code: 'UPLOAD_NOT_FOUND', retryable: true })
    upload.status = 'completed'
    const idempotent = batch.photos.has(chunkFinalizeMatch[2])
    if (!idempotent) batch.photos.set(chunkFinalizeMatch[2], { metadata: upload.metadata, status: 'server_saved' })
    return { ok: true, idempotent, photo: { photo_uuid: chunkFinalizeMatch[2], status: 'server_saved' }, upload: { upload_id: `mock-upload-${chunkFinalizeMatch[2]}`, status: upload.status } } as T
  }
  const analyzeMatch = path.match(/^\/batches\/([^/]+)\/analyze$/)
  if (analyzeMatch && method === 'POST') {
    const batch = batches.get(analyzeMatch[1])
    batch?.photos.forEach((photo) => {
      photo.status = 'needs_review'
      photo.match_candidates = [{ unit_code: 'YNLQ-DY-001', unit_name: '拦河闸进口段', process_name: '钢筋安装', confidence: 0.93, reason: '文件名和水印一致' }]
    })
    return { ok: true, batch: { batch_id: batch?.id, client_batch_id: batch?.payload.client_batch_id, status: 'needs_review', photos: batch ? [...batch.photos.entries()].map(([photo_uuid, photo]) => ({ photo_uuid, ...photo })) : [] } } as T
  }
  const assignmentsMatch = path.match(/^\/batches\/([^/]+)\/assignments$/)
  if (assignmentsMatch && method === 'PATCH') {
    const batch = batches.get(assignmentsMatch[1])
    return { ok: true, batch: { batch_id: batch?.id, client_batch_id: batch?.payload.client_batch_id, status: 'needs_review', photos: batch ? [...batch.photos.entries()].map(([photo_uuid, photo]) => ({ photo_uuid, ...photo })) : [] } } as T
  }
  const commitMatch = path.match(/^\/batches\/([^/]+)\/commit$/)
  if (commitMatch && method === 'POST') {
    const batch = batches.get(commitMatch[1])
    if (batch) batch.committed = true
    return { ok: true, batch: { batch_id: batch?.id, client_batch_id: batch?.payload.client_batch_id, status: 'desktop_pending', photos: batch ? [...batch.photos.entries()].map(([photo_uuid, photo]) => ({ photo_uuid, ...photo, status: 'desktop_pending' })) : [] } } as T
  }
  throw Object.assign(new Error(`Mock API 尚未实现：${method} ${path}`), { code: 'MOCK_NOT_IMPLEMENTED', retryable: false })
}

export async function mockUpload(batchId: string, metadata: PhotoUploadMetadata): Promise<{ ok: true; idempotent: boolean; photo: Record<string, unknown> }> {
  await new Promise((resolve) => setTimeout(resolve, 120))
  const batch = batches.get(batchId)
  if (!batch) throw Object.assign(new Error('上传批次不存在'), { code: 'BATCH_NOT_FOUND', retryable: false })
  const idempotent = batch.photos.has(metadata.photo_uuid)
  if (!idempotent) batch.photos.set(metadata.photo_uuid, { metadata, status: 'server_saved' })
  return { ok: true, idempotent, photo: { photo_uuid: metadata.photo_uuid, status: 'server_saved', title: metadata.title, photo_date: metadata.photo_date } }
}
