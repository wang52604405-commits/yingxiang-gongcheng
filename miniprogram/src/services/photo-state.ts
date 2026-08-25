import type { PhotoStatus } from '@/types/domain'

export const PHOTO_TRANSITIONS: Record<PhotoStatus, readonly PhotoStatus[]> = {
  local_ready: ['uploading', 'failed'],
  uploading: ['server_saved', 'local_ready', 'failed'],
  server_saved: ['analyzing', 'desktop_pending', 'failed'],
  analyzing: ['needs_review', 'desktop_pending', 'failed'],
  needs_review: ['desktop_pending', 'failed'],
  desktop_pending: ['desktop_imported', 'failed'],
  desktop_imported: [],
  failed: ['local_ready', 'uploading', 'server_saved', 'analyzing', 'needs_review', 'desktop_pending'],
}

export function canTransition(from: PhotoStatus, to: PhotoStatus): boolean {
  return PHOTO_TRANSITIONS[from].includes(to)
}

export function transitionPhoto(from: PhotoStatus, to: PhotoStatus): PhotoStatus {
  if (!canTransition(from, to)) throw new Error(`非法照片状态变化：${from} -> ${to}`)
  return to
}

export function recoverInterruptedStatus(status: PhotoStatus): PhotoStatus {
  return status === 'uploading' ? 'local_ready' : status
}

export const STATUS_LABELS: Record<PhotoStatus, string> = {
  local_ready: '原图待中转',
  uploading: '原图上传中',
  server_saved: '服务器已保存',
  analyzing: '正在识别',
  needs_review: '需要确认',
  desktop_pending: '电脑待归档',
  desktop_imported: '电脑已归档',
  failed: '需要处理',
}
