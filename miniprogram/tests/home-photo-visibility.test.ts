import { describe, expect, it } from 'vitest'
import { countTodayCaptures, visibleLocalHomePhotos } from '@/services/home-photo-visibility'
import type { CloudPhoto, LocalPhoto, PhotoStatus } from '@/types/domain'

function localPhoto(photoUuid: string, status: PhotoStatus, capturedAt = '2026-08-28T08:00:00'): LocalPhoto {
  return {
    photo_uuid: photoUuid,
    status,
    client_captured_at: capturedAt,
    created_at: capturedAt,
  } as LocalPhoto
}

function cloudPhoto(photoUuid: string, capturedAt = '2026-08-28T09:00:00'): CloudPhoto {
  return {
    photo_uuid: photoUuid,
    status: 'desktop_pending',
    captured_at: capturedAt,
    scope: 'engineering',
    title: '',
    photo_date: '2026-08-28',
  }
}

describe('工作台本地影像可见性', () => {
  it('服务器最近列表为空时，本地兜底不回显已归档记录', () => {
    const photos = [
      localPhoto('deleted-on-desktop', 'desktop_imported'),
      localPhoto('waiting-upload', 'local_ready'),
      localPhoto('server-saved', 'server_saved'),
    ]

    expect(visibleLocalHomePhotos(photos).map((photo) => photo.photo_uuid)).toEqual(['waiting-upload', 'server-saved'])
  })

  it('今日采集排除已归档本地记录，但保留云端影像并按 UUID 去重', () => {
    const local = [
      localPhoto('deleted-on-desktop', 'desktop_imported'),
      localPhoto('same-photo', 'server_saved'),
      localPhoto('yesterday', 'local_ready', '2026-08-27T23:00:00'),
    ]
    const cloud = [cloudPhoto('same-photo'), cloudPhoto('cloud-only')]

    expect(countTodayCaptures(cloud, local, '2026-08-28T12:00:00')).toBe(2)
    expect(countTodayCaptures([], [local[0]], '2026-08-28T12:00:00')).toBe(0)
  })
})
