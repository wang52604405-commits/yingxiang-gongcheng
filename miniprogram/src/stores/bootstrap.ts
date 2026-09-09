import { reactive } from 'vue'
import { mobileApi } from '@/api/mobile'
import type { BootstrapResponse, ProjectSummary } from '@/types/domain'
import { selectionStorage } from './selection'

const BOOTSTRAP_KEY = 'engineering-image:bootstrap:v1'
let viewGeneration = 0
let requestVersion = 0
const keyFor = (accountId: string | number) => `${BOOTSTRAP_KEY}:account:${String(accountId)}`

export const bootstrapState = reactive<{
  ready: boolean
  loading: boolean
  projects: ProjectSummary[]
  currentProject: ProjectSummary | null
  queue: Record<string, number>
  recentUploads: BootstrapResponse['recent_uploads']
  serverTime: string
}>({ ready: false, loading: false, projects: [], currentProject: null, queue: {}, recentUploads: [], serverTime: '' })

export function applyBootstrap(accountId: string | number, response: BootstrapResponse, preferredProjectId = ''): void {
  selectionStorage.setOwner(accountId)
  const selectedProject = selectionStorage.getProject()
  const activeProject = response.projects.find((project) => String(project.id) === String(preferredProjectId))
    || response.projects.find((project) => String(project.id) === String(selectedProject.id))
    || response.projects.find((project) => String(project.id) === String(response.current_project?.id || ''))
    || response.projects[0]
    || null
  bootstrapState.projects = response.projects
  bootstrapState.currentProject = activeProject
  bootstrapState.queue = response.queue
  bootstrapState.recentUploads = response.recent_uploads
  bootstrapState.serverTime = response.server_time
  bootstrapState.ready = true
  if (activeProject) selectionStorage.setProject(activeProject)
  else selectionStorage.clearProject()
  uni.setStorageSync(keyFor(accountId), response)
}

export function hydrateBootstrap(accountId: string | number): BootstrapResponse | null {
  selectionStorage.setOwner(accountId)
  const cached = uni.getStorageSync(keyFor(accountId)) as BootstrapResponse | null
  if (cached?.ok) applyBootstrap(accountId, cached)
  return cached || null
}

export async function loadBootstrap(accountId: string | number, preferredProjectId = '', canApply: () => boolean = () => true): Promise<BootstrapResponse> {
  const generation = viewGeneration
  const request = ++requestVersion
  bootstrapState.loading = true
  try {
    const response = await mobileApi.bootstrap()
    if (generation !== viewGeneration || !canApply()) throw new Error('登录状态已改变，已忽略旧响应')
    if (String(response.account?.id || '') !== String(accountId)) throw new Error('登录账号已改变，请重新验证')
    applyBootstrap(accountId, response, preferredProjectId)
    return response
  } finally {
    if (request === requestVersion) bootstrapState.loading = false
  }
}

export function clearBootstrapView(): void {
  viewGeneration += 1
  requestVersion += 1
  bootstrapState.loading = false
  bootstrapState.ready = false
  bootstrapState.projects = []
  bootstrapState.currentProject = null
  bootstrapState.queue = {}
  bootstrapState.recentUploads = []
  bootstrapState.serverTime = ''
}
