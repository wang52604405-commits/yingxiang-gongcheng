import { reactive } from 'vue'
import { mobileApi } from '@/api/mobile'
import type { BootstrapResponse, ProjectSummary } from '@/types/domain'
import { selectionStorage } from './selection'

const BOOTSTRAP_KEY = 'engineering-image:bootstrap:v1'
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

export function applyBootstrap(accountId: string | number, response: BootstrapResponse): void {
  selectionStorage.setOwner(accountId)
  const selectedProject = selectionStorage.getProject()
  const activeProject = response.projects.find((project) => String(project.id) === String(selectedProject.id))
    || response.current_project
  bootstrapState.projects = response.projects
  bootstrapState.currentProject = activeProject
  bootstrapState.queue = response.queue
  bootstrapState.recentUploads = response.recent_uploads
  bootstrapState.serverTime = response.server_time
  bootstrapState.ready = true
  if (activeProject) selectionStorage.setProject(activeProject)
  uni.setStorageSync(keyFor(accountId), response)
}

export function hydrateBootstrap(accountId: string | number): BootstrapResponse | null {
  selectionStorage.setOwner(accountId)
  const cached = uni.getStorageSync(keyFor(accountId)) as BootstrapResponse | null
  if (cached?.ok) applyBootstrap(accountId, cached)
  return cached || null
}

export async function loadBootstrap(accountId: string | number): Promise<BootstrapResponse> {
  bootstrapState.loading = true
  try {
    const response = await mobileApi.bootstrap()
    applyBootstrap(accountId, response)
    return response
  } finally {
    bootstrapState.loading = false
  }
}

export function clearBootstrapView(): void {
  bootstrapState.ready = false
  bootstrapState.projects = []
  bootstrapState.currentProject = null
  bootstrapState.queue = {}
  bootstrapState.recentUploads = []
  bootstrapState.serverTime = ''
}
