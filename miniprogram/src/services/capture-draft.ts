import type { UploadDraft } from '@/types/domain'

export interface CaptureItem {
  path: string
  sourcePath: string
  size: number
  date: string
  source: 'camera' | 'album'
  overrides: Partial<UploadDraft>
}
export interface CaptureDraft {
  items: CaptureItem[]
  title: string
  photographer: string
  draft: UploadDraft
}
const key = (kind: string, owner: string, project: string) => `engineering-image:capture-${kind}:v2:${encodeURIComponent(owner)}:${encodeURIComponent(project)}`
export const captureDraftStorage = {
  read(owner: string, project: string): CaptureDraft | null {
    if (!owner || !project) return null
    return uni.getStorageSync(key('draft', owner, project)) || null
  },
  save(owner: string, project: string, value: CaptureDraft) {
    if (owner && project) uni.setStorageSync(key('draft', owner, project), JSON.parse(JSON.stringify(value)))
  },
  clear(owner: string, project: string) { uni.removeStorageSync(key('draft', owner, project)) },
  last(owner: string, project: string): CaptureDraft | null { return uni.getStorageSync(key('last', owner, project)) || null },
  remember(owner: string, project: string, value: CaptureDraft) {
    // The previous batch is a reusable form preset, never another copy of its photos or date.
    uni.setStorageSync(key('last', owner, project), { ...value, items: [] })
  },
}
export function localDate(value = new Date()): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}
export function captureOverrides(item: CaptureItem, title: string, photographer: string): Partial<UploadDraft> {
  return { capture_item_id: item.path, title: title.trim(), photographer: photographer.trim(), photo_date: item.date, capture_source: item.source, ...item.overrides, assignment_explicit: Boolean(item.overrides.assignment) }
}
