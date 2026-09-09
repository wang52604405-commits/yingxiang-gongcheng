import { apiRequest } from '@/api/client'
import { API_MODE } from '@/config/env'
import { selectionStorage } from '@/stores/selection'
export interface ProjectWatermarkSettings { logo_id: string; contractor: string }
export interface ProjectWatermarkResponse { settings: ProjectWatermarkSettings; can_manage: boolean }
const pending = new Map<string,Promise<ProjectWatermarkResponse>>()
const key = (project: string) => `engineering-image:project-watermark:v1:${selectionStorage.getOwner()}:${project}`
export function cachedProjectWatermark(project: string): ProjectWatermarkResponse {
  return uni.getStorageSync(key(project)) || {settings:{logo_id:'',contractor:''},can_manage:false}
}
export async function readProjectWatermark(project: string): Promise<ProjectWatermarkResponse> {
  const storageKey=key(project)
  const existing=pending.get(storageKey);if(existing) return existing
  const task=(async () => {
    const value = API_MODE === 'mock' ? {...cachedProjectWatermark(project),can_manage:selectionStorage.getProject().can_manage_members !== false} : await apiRequest<ProjectWatermarkResponse>('GET',`/projects/${encodeURIComponent(project)}/watermark-settings`)
    uni.setStorageSync(storageKey,value);return value
  })()
  pending.set(storageKey,task)
  try {return await task} finally {if(pending.get(storageKey)===task)pending.delete(storageKey)}
}
export async function saveProjectWatermark(project: string, settings: ProjectWatermarkSettings): Promise<ProjectWatermarkResponse> {
  const storageKey=key(project)
  const value = API_MODE === 'mock' ? {settings,can_manage:true} : await apiRequest<ProjectWatermarkResponse>('PATCH',`/projects/${encodeURIComponent(project)}/watermark-settings`,settings)
  uni.setStorageSync(storageKey,value);return value
}
