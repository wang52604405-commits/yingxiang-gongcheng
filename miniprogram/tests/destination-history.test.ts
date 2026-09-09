import { beforeEach, describe, expect, it, vi } from 'vitest'
import { consumePhotoEditDestination, flattenDestinations, getDestinationHistory, reconcileDestination, rememberDestination, setPhotoEditDestination, toggleFavoriteDestination } from '@/services/destination-history'
import type { DestinationSelection } from '@/stores/selection'
import type { ProjectNode } from '@/types/domain'

const destination: DestinationSelection = { scope: 'engineering', assignment: { unit_project_code: 'up', part_code: 'part', unit_code: 'unit', unit_name: '旧名称', process_name: '模板' } }
const tree: ProjectNode[] = [{ code: 'contract', name: '合同', type: 'contract', children: [{ code: 'up', name: '单位', type: 'unit_project', children: [{ code: 'part', name: '分部', type: 'part', children: [{ code: 'unit', name: '最新单元名', type: 'unit', processes: ['模板', '钢筋'] }] }] }] }]
beforeEach(() => {
  const data = new Map<string, unknown>()
  vi.stubGlobal('uni', {
    getStorageSync: (key: string) => data.get(key),
    setStorageSync: (key: string, value: unknown) => data.set(key, structuredClone(value)),
    removeStorageSync: (key: string) => data.delete(key),
  })
})
describe('destination shortcuts and single-photo handoff', () => {
  it('keeps recents and favorites isolated by account and project, and deduplicates recents', () => {
    rememberDestination('alice', 'one', destination)
    rememberDestination('alice', 'one', { ...destination, assignment: { ...destination.assignment, unit_name: '更新名称' } })
    toggleFavoriteDestination('alice', 'one', destination)
    expect(getDestinationHistory('alice', 'one').recent).toHaveLength(1)
    expect(getDestinationHistory('bob', 'one')).toEqual({ recent: [], favorites: [] })
    expect(getDestinationHistory('alice', 'two')).toEqual({ recent: [], favorites: [] })
    toggleFavoriteDestination('alice', 'one', destination)
    expect(getDestinationHistory('alice', 'one').favorites).toEqual([])
    expect(getDestinationHistory('alice', 'one').recent[0].assignment.unit_name).toBe('更新名称')
  })
  it('refreshes full paths and assignments from live hierarchy and rejects retired destinations/processes', () => {
    const nodes = flattenDestinations(tree)
    expect(nodes.at(-1)?.pathLabel).toBe('合同 / 单位 / 分部')
    expect(reconcileDestination(destination, nodes)?.assignment.unit_name).toBe('最新单元名')
    expect(reconcileDestination(destination, [])).toBeNull()
    expect(reconcileDestination({ ...destination, assignment: { ...destination.assignment, process_name: '已撤销工序' } }, nodes)).toBeNull()
    expect(reconcileDestination({ ...destination, assignment: { ...destination.assignment, process_name: '' } }, nodes)).toBeNull()
    expect(flattenDestinations([{ ...tree[0], active: false }])).toEqual([])
  })
  it('does not confuse identically coded units under different parts', () => {
    const nodes = flattenDestinations(tree)
    expect(reconcileDestination({ ...destination, assignment: { ...destination.assignment, part_code: 'another-part' } }, nodes)).toBeNull()
  })
  it('consumes a photo edit exactly once without crossing project or account boundaries', () => {
    setPhotoEditDestination('alice', 'one', destination)
    expect(consumePhotoEditDestination('bob', 'one')).toBeNull()
    expect(consumePhotoEditDestination('alice', 'two')).toBeNull()
    expect(consumePhotoEditDestination('alice', 'one')?.assignment).toEqual(destination.assignment)
    expect(consumePhotoEditDestination('alice', 'one')).toBeNull()
    expect(getDestinationHistory('alice', 'one').recent).toEqual([])
  })
})
