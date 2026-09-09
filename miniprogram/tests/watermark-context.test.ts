import { beforeEach, describe, expect, it } from 'vitest'
import { consumeWatermarkContext, setWatermarkContext, watermarkContextMatches, watermarkUploadDraft } from '@/services/watermark-context'
const input = { sourcePath: '/saved/photo.jpg', sourceQuality: 'original' as const, sourceKind: 'album' as const, project: '工程', title: '模板', photographer: '张三', photoDate: '' }
const data = new Map<string, any>()
beforeEach(() => {
  data.clear()
  ;(globalThis as any).uni = { getStorageSync: (key: string) => data.get(key), setStorageSync: (key: string, value: unknown) => data.set(key, value), removeStorageSync: (key: string) => data.delete(key) }
})
describe('watermark editor handoff', () => {
  it('consumes exactly once and cannot cross account or selected-project boundaries', () => {
    setWatermarkContext('A', 'P', input, 1_000)
    expect(consumeWatermarkContext('B', 'P', 1_001)).toBeNull()
    expect(consumeWatermarkContext('A', 'Q', 1_001)).toBeNull()
    const value = consumeWatermarkContext('A', 'P', 1_001)!
    expect(value.sourcePath).toBe('/saved/photo.jpg')
    expect(watermarkContextMatches(value, 'A', 'P')).toBe(true)
    expect(watermarkContextMatches(value, 'B', 'P')).toBe(false)
    expect(watermarkContextMatches(value, 'A', 'Q')).toBe(false)
    expect(consumeWatermarkContext('A', 'P', 1_002)).toBeNull()
  })
  it('rejects expired temporary handoffs and keeps unknown dates blank', () => {
    setWatermarkContext('A', 'P', input, 1_000)
    expect(consumeWatermarkContext('A', 'P', 1_001)?.photoDate).toBe('')
    setWatermarkContext('A', 'P', input, 1_000)
    expect(consumeWatermarkContext('A', 'P', 301_001)).toBeNull()
  })
  it('preserves preview provenance and strips location/extra objects from navigation storage', () => {
    setWatermarkContext('A', 'P', { ...input, sourceQuality: 'preview', location: { latitude: 30, longitude: 120 }, buffer: 'unwanted' } as any, 1_000)
    const value = consumeWatermarkContext('A', 'P', 1_001)!
    expect(value.sourceQuality).toBe('preview')
    expect(value).not.toHaveProperty('location')
    expect(value).not.toHaveProperty('buffer')
  })
  it('uploads the edited watermark as an automatic classification draft without forcing a unit or changing the source', () => {
    const context = { ...input, owner: 'A', projectId: 'P', scope: 'engineering' as const, category: 'supervision' as const }
    const before = JSON.stringify(context)
    const draft = watermarkUploadDraft(context, { title: ' 更新题名 ', photographer: ' 李四 ', photoDate: '2026-09-09', sitePart: ' 一号闸室底板 ' }, '实际归档工程', 'watermark:/temp/generated.jpg')
    expect(draft).toMatchObject({ project_id: 'P', project_name: '实际归档工程', category: 'supervision', mode: 'auto', title: '更新题名', photographer: '李四', photo_date: '2026-09-09', site_part: '一号闸室底板', capture_item_id: 'watermark:/temp/generated.jpg' })
    expect(draft).not.toHaveProperty('assignment')
    expect(JSON.stringify(context)).toBe(before)
    expect(context.sourcePath).toBe('/saved/photo.jpg')
  })

})

it('相册手填时间覆盖旧时间而不改原图信息', () => {
  const draft = watermarkUploadDraft({ ...input, owner: 'A', projectId: 'P', capturedAt: '2026-09-01T12:00:00' }, { title: '', photographer: '张三', photoDate: '2026-09-08', sitePart: '', capturedAt: '2026-09-08T15:30:00' }, '工程', 'test')
  expect(draft.captured_at).toBe('2026-09-08T15:30:00')
  expect(draft.capture_source).toBe('album')
})
