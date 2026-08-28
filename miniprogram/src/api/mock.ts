import { CURRENT_PROJECT } from '@/config/env'
import type { BootstrapResponse, CloudPhoto, MatchCandidate, PhotoRequirement, ProjectNode, ProjectSummary } from '@/types/domain'
import type { CreateBatchPayload, PhotoUploadMetadata } from './contracts'

interface MockBatch {
  id: string
  payload: CreateBatchPayload
  photos: Map<string, { metadata: PhotoUploadMetadata; status: string; match_candidates?: MatchCandidate[] }>
  committed: boolean
}

const projects: ProjectSummary[] = [{ ...CURRENT_PROJECT, revision: 1, unit_count: 888 }]
const rawProject = (project: ProjectSummary) => ({ id: project.id, project_id: project.id, project_code: project.code, project_name: project.name, revision: project.revision || 0, metadata: { unit_count: project.unit_count || 0 } })
const batches = new Map<string, MockBatch>()
const batchByClientId = new Map<string, string>()
const chunkUploads = new Map<string, { metadata: PhotoUploadMetadata; chunkSize: number; totalChunks: number; uploaded: Set<number>; status: string }>()

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
  { photo_uuid: 'demo-1', title: '钢筋安装检查', photo_date: '2026-08-25', scope: 'engineering', category: 'construction', unit_code: 'YNLQ-DY-001', unit_name: '拦河闸进口段', process_name: '钢筋安装', status: 'desktop_imported', created_at: '2026-08-25T01:28:00Z' },
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

const mockAccount = { id: 'mock-account', username: '体验账号', display_name: '工程资料员', role: '资料员' }

function mockBootstrap(): BootstrapResponse {
  return {
    ok: true,
    account: mockAccount,
    server_time: new Date().toISOString(),
    current_project: rawProject(projects[0]) as any,
    projects: projects.map(rawProject) as any,
    queue: { desktop_pending: 1 },
    recent_uploads: samplePhotos.slice(0, 3),
  }
}

export async function mockRequest<T>(method: string, path: string, data?: unknown): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, 80))
  if (path === '/auth/account-login' && method === 'POST') {
    return { ok: true, account: mockAccount, binding_intent: 'mock-binding-intent' } as T
  }
  if (path === '/auth/wechat-login' && method === 'POST') {
    return { ok: true, token: 'mock-token', account: mockAccount, bootstrap: mockBootstrap() } as T
  }
  if (path === '/auth/wechat-bind-confirm' && method === 'POST') {
    return { ok: true, token: 'mock-token', account: mockAccount, bootstrap: mockBootstrap() } as T
  }
  if (path === '/bootstrap' && method === 'GET') {
    return mockBootstrap() as T
  }
  if (path === '/projects' && method === 'GET') return { ok: true, projects: projects.map(rawProject) } as T
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
