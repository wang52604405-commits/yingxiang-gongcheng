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

type ServerWatermarkResponse = {
  settings?: { logo_id?: string; contractor?: string }
  can_manage?: boolean
}

const LOCATION_MARK = ' §§LOCATION§§ '
const cache = new Map<string, ProjectWatermarkResponse>()
const defaults = (): ProjectWatermarkResponse => ({ settings: { logo_id: '', contractor: '', location_text: '' }, can_manage: false })

function unpackContractor(raw: unknown): { contractor: string; location_text: string } {
  const text = String(raw || '')
  const index = text.indexOf(LOCATION_MARK)
  if (index < 0) return { contractor: text, location_text: '' }
  return { contractor: text.slice(0, index).trim(), location_text: text.slice(index + LOCATION_MARK.length).trim() }
}
function normalize(value?: ServerWatermarkResponse | null): ProjectWatermarkResponse {
  const packed = unpackContractor(value?.settings?.contractor)
  return { settings: { logo_id: String(value?.settings?.logo_id || ''), ...packed }, can_manage: Boolean(value?.can_manage) }
}
function packContractor(settings: ProjectWatermarkSettings): string {
  const contractor = settings.contractor.trim()
  const location = settings.location_text.trim()
  const packed = location ? `${contractor}${LOCATION_MARK}${location}` : contractor
  if (packed.length > 120) throw new Error('施工单位和固定拍摄地点合计过长，请适当简化')
  return packed
}

export function cachedProjectWatermark(projectId: string): ProjectWatermarkResponse {
  return cache.get(String(projectId || '')) || defaults()
}
export async function readProjectWatermark(projectId: string): Promise<ProjectWatermarkResponse> {
  const id = String(projectId || '')
  if (!id) return defaults()
  const response = normalize(await mobileApi.get<ServerWatermarkResponse>(`/projects/${encodeURIComponent(id)}/watermark-settings`))
  cache.set(id, response)
  return response
}
export async function saveProjectWatermark(projectId: string, settings: ProjectWatermarkSettings): Promise<ProjectWatermarkResponse> {
  const id = String(projectId || '')
  if (!id) throw new Error('请先选择工程')
  const raw = await mobileApi.patch<ServerWatermarkResponse>(`/projects/${encodeURIComponent(id)}/watermark-settings`, { logo_id: settings.logo_id, contractor: packContractor(settings) })
  const response = normalize(raw)
  cache.set(id, response)
  return response
}
