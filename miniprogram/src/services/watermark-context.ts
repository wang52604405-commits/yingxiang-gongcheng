import type { Scope, PhotoCategory, UploadDraft } from '@/types/domain'
export interface WatermarkContext {
  owner: string
  projectId: string
  sourcePath: string
  sourceQuality: 'original' | 'preview'
  sourceKind: 'camera' | 'album' | 'detail'
  scope?: Scope
  category?: PhotoCategory
  sitePart?: string
  project: string
  title: string
  photographer: string
  photoDate: string
  capturedAt?: string
  unitProjectName?: string
  partName?: string
  unitName?: string
}
type WatermarkInput = Omit<WatermarkContext, 'owner' | 'projectId'>
const key = (owner: string, projectId: string) => `engineering-image:watermark-context:v1:${encodeURIComponent(owner)}:${encodeURIComponent(projectId)}`
const TTL = 5 * 60 * 1000

/** The one-time handoff contains image metadata only; location is never stored here. */
export function setWatermarkContext(owner: string, projectId: string, input: WatermarkInput, now = Date.now()): void {
  if (!owner || !projectId || !input.sourcePath) throw new Error('请重新选择工程和照片')
  const value: WatermarkContext = {
    owner, projectId, sourcePath: input.sourcePath, sourceQuality: input.sourceQuality,
    sourceKind: input.sourceKind, scope: input.scope || 'engineering', category: input.category, sitePart: input.sitePart || '', project: input.project, title: input.title,
    photographer: input.photographer, photoDate: input.photoDate, capturedAt: input.capturedAt || '', unitProjectName: input.unitProjectName || '', partName: input.partName || '', unitName: input.unitName || '',
  }
  uni.setStorageSync(key(owner, projectId), { value, expiresAt: now + TTL })
}
export function consumeWatermarkContext(owner: string, projectId: string, now = Date.now()): WatermarkContext | null {
  if (!owner || !projectId) return null
  const storageKey = key(owner, projectId)
  const stored = uni.getStorageSync(storageKey) as { value?: WatermarkContext; expiresAt?: number } | undefined
  uni.removeStorageSync(storageKey)
  return stored?.value && Number(stored.expiresAt) > now && watermarkContextMatches(stored.value, owner, projectId) ? stored.value : null
}
export function watermarkContextMatches(context: WatermarkContext, owner: string, projectId: string): boolean {
  return Boolean(owner && projectId && context.owner === owner && context.projectId === projectId && context.sourcePath)
}

function normalizedPhotoDate(photoDate?: string, capturedAt?: string): string {
  const direct = String(photoDate || '').trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(direct)) return direct
  const source = String(capturedAt || '').trim()
  const date = new Date(source)
  if (!Number.isFinite(date.getTime())) return ''
  const two = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}`
}

export function watermarkUploadDraft(context: WatermarkContext, fields: { title: string; photographer: string; photoDate: string; sitePart: string; capturedAt?: string }, projectName: string, captureId: string): UploadDraft {
  const capturedAt = fields.capturedAt || context.capturedAt || ''
  return { project_id: context.projectId, project_name: projectName, scope: context.scope || 'engineering', category: context.scope === 'other' ? undefined : context.category || 'construction', mode: 'auto', auto_delivery: true, captured_at: capturedAt, capture_source: context.sourceKind === 'camera' ? 'camera' : 'album', title: fields.title.trim(), photographer: fields.photographer.trim(), photo_date: normalizedPhotoDate(fields.photoDate, capturedAt), site_part: fields.sitePart.trim(), capture_item_id: captureId }
}
