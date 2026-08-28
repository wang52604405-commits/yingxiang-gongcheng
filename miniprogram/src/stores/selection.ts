import { API_MODE, CURRENT_PROJECT, EMPTY_PROJECT } from '@/config/env'
import type { Assignment, CaptureRequirementRef, PhotoCategory, ProjectSummary, Scope, UploadMode } from '@/types/domain'

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

export interface UploadPreset {
  scope?: Scope
  category?: PhotoCategory
  mode?: UploadMode
  requirement?: CaptureRequirementRef
}

export const selectionStorage = {
  setOwner: (accountId: string | number) => { activeOwner = String(accountId) },
  clearOwner: () => { activeOwner = '' },
  getOwner: () => activeOwner,
  getProject: () => uni.getStorageSync(ownerKey(PROJECT_KEY)) || (API_MODE === 'mock' ? CURRENT_PROJECT : EMPTY_PROJECT),
  hasProject: () => Boolean((uni.getStorageSync(ownerKey(PROJECT_KEY)) || (API_MODE === 'mock' ? CURRENT_PROJECT : null))?.id),
  clearProject: () => {
    uni.removeStorageSync(ownerKey(PROJECT_KEY))
    uni.removeStorageSync(ownerKey(DESTINATION_KEY))
    uni.removeStorageSync(ownerKey(UPLOAD_PRESET_KEY))
  },
  setProject: (project: ProjectSummary) => {
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
  getUploadPreset: (): UploadPreset => uni.getStorageSync(ownerKey(UPLOAD_PRESET_KEY)) || {},
  setUploadPreset: (value: UploadPreset) => uni.setStorageSync(ownerKey(UPLOAD_PRESET_KEY), value),
}
