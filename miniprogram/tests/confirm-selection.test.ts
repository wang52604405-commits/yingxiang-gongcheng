import { beforeEach, describe, expect, it } from 'vitest'
import { selectionStorage } from '@/stores/selection'
import { createConfirmSelectionSession, initialConfirmAssignment } from '@/services/confirm-selection'
import type { UploadDraft } from '@/types/domain'

describe('确认页单次选择与逐张归属', () => {
  beforeEach(() => {
    const store = new Map<string, unknown>()
    ;(globalThis as any).uni = { getStorageSync: (key: string) => store.get(key), setStorageSync: (key: string, value: unknown) => store.set(key, value), removeStorageSync: (key: string) => store.delete(key) }
    selectionStorage.setOwner('a')
  })
  it('历史批次选择不自动套用，取消不套用，仅接收本次选择一次', () => {
    const session = createConfirmSelectionSession()
    const old = { project_id: 'p', scope: 'engineering' as const, assignment: { unit_code: 'old' } }
    selectionStorage.setConfirmDestination(old)
    expect(session.consume('p')).toBeNull()
    session.begin('p')
    expect(session.consume('p')).toBeNull()
    session.begin('p')
    selectionStorage.setConfirmDestination({ ...old, assignment: { unit_code: 'new' } })
    expect(session.consume('p')?.assignment.unit_code).toBe('new')
    expect(session.consume('p')).toBeNull()
  })
  it('账号或工程切换后不接收旧选择', () => {
    const session = createConfirmSelectionSession()
    session.begin('p')
    selectionStorage.setOwner('b')
    selectionStorage.setConfirmDestination({ project_id: 'p', scope: 'engineering', assignment: { unit_code: 'b' } })
    expect(session.consume('p')).toBeNull()
    session.begin('p')
    expect(session.consume('q')).toBeNull()
  })
  it('单张明确指定归属优先于识别，普通批次设置仍可使用识别建议', () => {
    const draft: UploadDraft = { project_id: 'p', scope: 'engineering', mode: 'auto', assignment: { unit_code: 'a', process_name: '模板' }, assignment_explicit: true }
    const candidate = { unit_code: 'b', process_name: '钢筋', confidence: 0.9 }
    expect(initialConfirmAssignment(draft, candidate)).toEqual(draft.assignment)
    expect(initialConfirmAssignment({ ...draft, assignment_explicit: false }, candidate)?.unit_code).toBe('b')
  })
})
