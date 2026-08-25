import { CURRENT_PROJECT } from '@/config/env'
import type { Assignment, PhotoCategory, Scope, UploadMode } from '@/types/domain'

const PROJECT_KEY = 'engineering-image:selected-project:v1'
const DESTINATION_KEY = 'engineering-image:selected-destination:v1'
const UPLOAD_PRESET_KEY = 'engineering-image:upload-preset:v1'
let activeOwner = ''

function ownerKey(base: string): string {
  return activeOwner ? `${base}:account:${activeOwner}` : `${base}:unbound`
}

export interface DestinationSelection {
  scope: Scope
  assignment: Assignment
}

export const selectionStorage = {
  setOwner: (accountId: string | number) => { activeOwner = String(accountId) },
  clearOwner: () => { activeOwner = '' },
  getOwner: () => activeOwner,
  getProject: () => uni.getStorageSync(ownerKey(PROJECT_KEY)) || CURRENT_PROJECT,
  setProject: (project: { id: string; code: string; name: string }) => {
    const projectKey = ownerKey(PROJECT_KEY)
    const previous = uni.getStorageSync(projectKey) as { id?: string } | null
    const changed = String(previous?.id || '') !== String(project.id)
    uni.setStorageSync(projectKey, project)
    if (changed) {
      uni.removeStorageSync(ownerKey(DESTINATION_KEY))
      uni.removeStorageSync(ownerKey(UPLOAD_PRESET_KEY))
    }
  },
  getDestination: (): DestinationSelection | null => uni.getStorageSync(ownerKey(DESTINATION_KEY)) || null,
  setDestination: (value: DestinationSelection) => uni.setStorageSync(ownerKey(DESTINATION_KEY), value),
  getUploadPreset: (): { scope?: Scope; category?: PhotoCategory; mode?: UploadMode } => uni.getStorageSync(ownerKey(UPLOAD_PRESET_KEY)) || {},
  setUploadPreset: (value: { scope?: Scope; category?: PhotoCategory; mode?: UploadMode }) => uni.setStorageSync(ownerKey(UPLOAD_PRESET_KEY), value),
}
