import { mobileApi } from '@/api/mobile'

export interface ProjectWatermarkSettings {
  logo_id: string
  contractor: string
  location_text: string
}
export interface ProjectWatermarkResponse {
  settings: ProjectWatermarkSettings
  can_manage: boolean
}

const cache = new Map<string, ProjectWatermarkResponse>()
const defaults = (): ProjectWatermarkResponse => ({
  settings: { logo_id: '', contractor: '', location_text: '' },
  can_manage: false,
})

function normalize(value?: Partial<ProjectWatermarkResponse> | null): ProjectWatermarkResponse {
  return {
    settings: {
      logo_id: String(value?.settings?.logo_id || ''),
      contractor: String(value?.settings?.contractor || ''),
      location_text: String(value?.settings?.location_text || ''),
    },
    can_manage: Boolean(value?.can_manage),
  }
}

export function cachedProjectWatermark(projectId: string): ProjectWatermarkResponse {
  return cache.get(String(projectId || '')) || defaults()
}

export async function readProjectWatermark(projectId: string): Promise<ProjectWatermarkResponse> {
  const id = String(projectId || '')
  if (!id) return defaults()
  const response = normalize(await mobileApi.get<ProjectWatermarkResponse>(`/projects/${encodeURIComponent(id)}/watermark-settings`))
  cache.set(id, response)
  return response
}

export async function saveProjectWatermark(projectId: string, settings: ProjectWatermarkSettings): Promise<ProjectWatermarkResponse> {
  const id = String(projectId || '')
  if (!id) throw new Error('请先选择工程')
  const response = normalize(await mobileApi.patch<ProjectWatermarkResponse>(`/projects/${encodeURIComponent(id)}/watermark-settings`, settings))
  cache.set(id, response)
  return response
}
