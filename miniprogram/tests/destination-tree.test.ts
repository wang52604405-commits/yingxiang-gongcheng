import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ owner: 'alice', projectTree: vi.fn(), otherTree: vi.fn() }))
vi.mock('@/api/mobile', () => ({ mobileApi: { projectTree: state.projectTree, otherTree: state.otherTree } }))
vi.mock('@/stores/selection', () => ({ selectionStorage: { getOwner: () => state.owner } }))
beforeEach(() => {
  vi.resetModules()
  state.owner = 'alice'
  state.projectTree.mockReset().mockResolvedValue({ ok: true, project: { id: 'one' }, nodes: [], units: [] })
  state.otherTree.mockReset().mockResolvedValue({ ok: true, project: { id: 'one' }, nodes: [], units: [] })
})
describe('destination tree request reuse', () => {
  it('deduplicates page requests but forces fresh validation when requested', async () => {
    const { loadDestinationTree } = await import('@/services/destination-tree')
    await Promise.all([loadDestinationTree('one', 'engineering'), loadDestinationTree('one', 'engineering')])
    await loadDestinationTree('one', 'engineering')
    expect(state.projectTree).toHaveBeenCalledTimes(1)
    await loadDestinationTree('one', 'engineering', true)
    expect(state.projectTree).toHaveBeenCalledTimes(2)
  })
  it('separates project, scope and account without leaking a previous account tree', async () => {
    const { loadDestinationTree } = await import('@/services/destination-tree')
    await loadDestinationTree('one', 'engineering')
    await loadDestinationTree('two', 'engineering')
    await loadDestinationTree('one', 'other')
    state.owner = 'bob'
    await loadDestinationTree('one', 'engineering')
    expect(state.projectTree).toHaveBeenCalledTimes(3)
    expect(state.otherTree).toHaveBeenCalledTimes(1)
  })
  it('does not retain failures and rejects results received after account switch', async () => {
    const { loadDestinationTree } = await import('@/services/destination-tree')
    state.projectTree.mockRejectedValueOnce(new Error('offline'))
    await expect(loadDestinationTree('one', 'engineering')).rejects.toThrow('offline')
    await loadDestinationTree('one', 'engineering')
    expect(state.projectTree).toHaveBeenCalledTimes(2)
    let resolve!: (value: unknown) => void
    state.projectTree.mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const result = loadDestinationTree('one', 'engineering', true)
    state.owner = 'bob'
    resolve({ ok: true, nodes: [] })
    await expect(result).rejects.toThrow('账号已切换')
  })
})
