import type { CloudPhoto, LocalPhoto } from '@/types/domain'

export function localDayKey(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

export function visibleLocalHomePhotos(photos: LocalPhoto[], limit = 3): LocalPhoto[] {
  return photos.filter((photo) => photo.status !== 'desktop_imported').slice(0, limit)
}

export function countTodayCaptures(cloudPhotos: CloudPhoto[], localPhotos: LocalPhoto[], today: string): number {
  const todayKey = localDayKey(today)
  const cloudIds = new Set<string>()
  let count = 0
  cloudPhotos.forEach((photo) => {
    if (localDayKey(photo.captured_at || photo.created_at || photo.photo_date) === todayKey) {
      cloudIds.add(photo.photo_uuid)
      count += 1
    }
  })
  localPhotos.forEach((photo) => {
    if (
      photo.status !== 'desktop_imported'
      && !cloudIds.has(photo.photo_uuid)
      && localDayKey(photo.client_captured_at || photo.created_at) === todayKey
    ) count += 1
  })
  return count
}
