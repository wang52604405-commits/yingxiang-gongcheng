import { beforeEach, describe, expect, it } from 'vitest'
import { selectionStorage } from '@/stores/selection'
import { applyBootstrap, bootstrapState, clearBootstrapView, hydrateBootstrap } from '@/stores/bootstrap'
import type { BootstrapResponse } from '@/types/domain'

describe('账号命名空间', () => {
  const storage = new Map<string, any>()

  beforeEach(() => {
    storage.clear()
    ;(globalThis as any).uni = {
      getStorageSync: (key: string) => storage.get(key),
      setStorageSync: (key: string, value: unknown) => storage.set(key, value),
      removeStorageSync: (key: string) => storage.delete(key),
    }
    selectionStorage.clearOwner()
    clearBootstrapView()
  })

  it('工程选择、采集目的地、图库筛选和上传预设按 account.id 隔离', () => {
    selectionStorage.setOwner('A')
    selectionStorage.setProject({ id: 'project-a', code: 'A', name: '甲工程' })
    selectionStorage.setDestination({ scope: 'engineering', assignment: { unit_code: 'A-001', unit_name: '甲单元' } })
    selectionStorage.setLibraryFilter({ scope: 'engineering', assignment: { unit_code: 'A-002', unit_name: '甲筛选单元' } })
    selectionStorage.setUploadPreset({ scope: 'engineering', category: 'construction', mode: 'direct' })

    selectionStorage.setOwner('B')
    expect(selectionStorage.getProject().id).not.toBe('project-a')
    expect(selectionStorage.getDestination()).toBeNull()
    expect(selectionStorage.getLibraryFilter()).toBeNull()
    selectionStorage.setProject({ id: 'project-b', code: 'B', name: '乙工程' })

    selectionStorage.setOwner('A')
    expect(selectionStorage.getProject().id).toBe('project-a')
    expect(selectionStorage.getDestination()?.assignment.unit_code).toBe('A-001')
    expect(selectionStorage.getLibraryFilter()?.assignment.unit_code).toBe('A-002')
    expect(selectionStorage.getUploadPreset()).toMatchObject({ category: 'construction', mode: 'direct' })
  })

  it('bootstrap 缓存按账号独立恢复', () => {
    const response = (id: string): BootstrapResponse => ({
      ok: true,
      account: { id, username: id },
      server_time: '2026-08-25T00:00:00Z',
      current_project: { id: `project-${id}`, code: id, name: `${id}工程` },
      projects: [{ id: `project-${id}`, code: id, name: `${id}工程` }],
      queue: { desktop_pending: id === 'A' ? 1 : 2 },
      recent_uploads: [],
    })
    applyBootstrap('A', response('A'))
    applyBootstrap('B', response('B'))
    clearBootstrapView()
    expect(hydrateBootstrap('A')?.current_project?.id).toBe('project-A')
    clearBootstrapView()
    expect(hydrateBootstrap('B')?.queue.desktop_pending).toBe(2)
  })

  it('切换工程清除旧单元和上传预设，同一工程刷新不误清除', () => {
    selectionStorage.setOwner('A')
    selectionStorage.setProject({ id: 'project-a', code: 'A', name: '甲工程' })
    selectionStorage.setDestination({ scope: 'engineering', assignment: { unit_code: 'A-001', unit_name: '甲单元' } })
    selectionStorage.setLibraryFilter({ scope: 'engineering', assignment: { unit_code: 'A-002', unit_name: '甲筛选单元' } })
    selectionStorage.setUploadPreset({ scope: 'engineering', category: 'supervision', mode: 'direct' })

    selectionStorage.setProject({ id: 'project-a', code: 'A', name: '甲工程（已刷新）' })
    expect(selectionStorage.getDestination()?.assignment.unit_code).toBe('A-001')
    expect(selectionStorage.getLibraryFilter()?.assignment.unit_code).toBe('A-002')
    expect(selectionStorage.getUploadPreset()).toMatchObject({ category: 'supervision', mode: 'direct' })

    selectionStorage.setProject({ id: 'project-b', code: 'B', name: '乙工程' })
    expect(selectionStorage.getDestination()).toBeNull()
    expect(selectionStorage.getLibraryFilter()).toBeNull()
    expect(selectionStorage.getUploadPreset()).toEqual({})
  })

  it('旧批次归档修复使用独立工程目的地，不覆盖当前采集与图库筛选', () => {
    selectionStorage.setOwner('A')
    selectionStorage.setProject({ id: 'project-current', code: 'NOW', name: '当前工程' })
    selectionStorage.setDestination({ scope: 'engineering', assignment: { unit_code: 'NOW-001', unit_name: '当前采集单元' } })
    selectionStorage.setLibraryFilter({ scope: 'engineering', assignment: { unit_code: 'NOW-002', unit_name: '当前图库筛选' } })
    selectionStorage.setConfirmDestination({
      scope: 'engineering',
      project_id: 'project-old',
      project_name: '旧工程',
      assignment: { unit_code: 'OLD-001', unit_name: '旧批次单元' },
    })

    expect(selectionStorage.getConfirmDestination('project-old')?.assignment.unit_code).toBe('OLD-001')
    expect(selectionStorage.getConfirmDestination('project-current')).toBeNull()
    expect(selectionStorage.getDestination()?.assignment.unit_code).toBe('NOW-001')
    expect(selectionStorage.getLibraryFilter()?.assignment.unit_code).toBe('NOW-002')
  })

  it('账号数据刷新时保留仍存在的已选工程，避免各 Tab 跳回服务端默认工程', () => {
    selectionStorage.setOwner('A')
    selectionStorage.setProject({ id: 'project-b', code: 'B', name: '乙工程' })
    const response: BootstrapResponse = {
      ok: true,
      account: { id: 'A', username: 'A' },
      server_time: '2026-08-25T00:00:00Z',
      current_project: { id: 'project-a', code: 'A', name: '甲工程' },
      projects: [
        { id: 'project-a', code: 'A', name: '甲工程' },
        { id: 'project-b', code: 'B', name: '乙工程（服务器刷新）' },
      ],
      queue: {},
      recent_uploads: [],
    }

    applyBootstrap('A', response)
    expect(bootstrapState.currentProject?.id).toBe('project-b')
    expect(selectionStorage.getProject()).toMatchObject({ id: 'project-b', name: '乙工程（服务器刷新）' })
  })

  it('真实账号没有服务器工程时清除旧选择，不伪造默认工程', () => {
    selectionStorage.setOwner('A')
    selectionStorage.setProject({ id: 'stale-project', code: 'STALE', name: '旧缓存工程' })
    applyBootstrap('A', {
      ok: true,
      account: { id: 'A', username: 'A' },
      server_time: '2026-08-25T00:00:00Z',
      current_project: null,
      projects: [],
      queue: {},
      recent_uploads: [],
    })
    expect(bootstrapState.currentProject).toBeNull()
    expect(selectionStorage.hasProject()).toBe(false)
    expect(selectionStorage.getProject()).toMatchObject({ id: '', name: '尚未选择工程' })
  })
})
