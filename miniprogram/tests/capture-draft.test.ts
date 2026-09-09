import { beforeEach, describe, expect, it } from 'vitest'
import { captureDraftStorage, captureOverrides, localDate, type CaptureDraft } from '@/services/capture-draft'

describe('采集草稿与批量资料', () => {
  const storage = new Map<string, unknown>()
  const sample = (): CaptureDraft => ({
    title: '混凝土浇筑', photographer: '张工',
    draft: { project_id: 'P1', scope: 'engineering', mode: 'direct' },
    items: [
      { path: '/saved/a', sourcePath: '/temp/a', size: 1200, date: '2026-08-01', source: 'album', overrides: {} },
      { path: '/saved/b', sourcePath: '/temp/b', size: 1300, date: '2026-08-02', source: 'album', overrides: { title: '模板检查', photographer: '李工' } },
    ],
  })
  beforeEach(() => {
    storage.clear()
    ;(globalThis as any).uni = {
      getStorageSync: (key: string) => storage.get(key),
      setStorageSync: (key: string, value: unknown) => storage.set(key, JSON.parse(JSON.stringify(value))),
      removeStorageSync: (key: string) => storage.delete(key),
    }
  })
  it('退出再进仍保留每张日期与单独修改，换账号和工程不会串资料', () => {
    const draft = sample()
    captureDraftStorage.save('A', 'P1', draft)
    draft.items[0].date = '2026-09-09'
    expect(captureDraftStorage.read('A', 'P1')?.items[0].date).toBe('2026-08-01')
    expect(captureDraftStorage.read('B', 'P1')).toBeNull()
    expect(captureDraftStorage.read('A', 'P2')).toBeNull()
    expect(captureDraftStorage.read('A', 'P1')?.items[1].overrides.photographer).toBe('李工')
  })
  it('批量题名不覆盖单张例外，也不把不同日期统一成今天', () => {
    const { items } = sample()
    expect(captureOverrides(items[0], '  浇筑  ', '张工')).toMatchObject({ title: '浇筑', photographer: '张工', photo_date: '2026-08-01' })
    expect(captureOverrides(items[1], '浇筑', '张工')).toMatchObject({ title: '模板检查', photographer: '李工', photo_date: '2026-08-02' })
    items[0].date = ''
    expect(captureOverrides(items[0], '', '').photo_date).toBe('')
  })
  it('沿用上批只记表单，不携带照片和上批拍摄日期', () => {
    captureDraftStorage.remember('A', 'P1', sample())
    expect(captureDraftStorage.last('A', 'P1')?.items).toEqual([])
    expect(captureDraftStorage.last('A', 'P1')?.photographer).toBe('张工')
    expect(captureDraftStorage.last('A', 'P2')).toBeNull()
  })
  it('日期按本地日历生成，不截取UTC日期', () => {
    expect(localDate(new Date(2026, 8, 9, 0, 5))).toBe('2026-09-09')
  })
})
