import { beforeEach, describe, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ bootstrap: vi.fn() }))
vi.mock('@/api/mobile', () => ({ mobileApi: { bootstrap: mocks.bootstrap } }))
beforeEach(() => {
  vi.resetModules()
  mocks.bootstrap.mockReset()
  const data = new Map<string, unknown>()
  vi.stubGlobal('uni', { getStorageSync: (key: string) => data.get(key), setStorageSync: (key: string, value: unknown) => data.set(key, value), removeStorageSync: (key: string) => data.delete(key) })
})
function response(owner: string): any {
  const project = { id: `${owner}:project`, name: `${owner}工程`, code: owner }
  return { ok: true, account: { id: owner, username: owner }, projects: [project], current_project: project, recent_uploads: [], queue: {}, server_time: '' }
}
describe('late bootstrap responses', () => {
  it('checks the auth guard before applying account, project or cached bootstrap', async () => {
    let finish!: (value: unknown) => void
    mocks.bootstrap.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const { loadBootstrap, bootstrapState } = await import('@/stores/bootstrap')
    const { selectionStorage } = await import('@/stores/selection')
    let stillCurrent = true
    const pending = loadBootstrap('A', '', () => stillCurrent)
    stillCurrent = false
    finish(response('A'))
    await expect(pending).rejects.toThrow('已忽略旧响应')
    expect(bootstrapState.projects).toEqual([])
    expect(selectionStorage.getOwner()).toBe('')
  })
  it('sign-out invalidates other page requests too, so late A cannot overwrite newly logged-in B', async () => {
    let finish!: (value: unknown) => void
    mocks.bootstrap.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const { loadBootstrap, applyBootstrap, clearBootstrapView, bootstrapState } = await import('@/stores/bootstrap')
    const { selectionStorage } = await import('@/stores/selection')
    applyBootstrap('A', response('A'))
    const pending = loadBootstrap('A')
    clearBootstrapView()
    applyBootstrap('B', response('B'))
    finish(response('A'))
    await expect(pending).rejects.toThrow('已忽略旧响应')
    expect(bootstrapState.currentProject?.id).toBe('B:project')
    expect(selectionStorage.getOwner()).toBe('B')
  })
  it('rejects a bootstrap whose verified account is not the requested account', async () => {
    mocks.bootstrap.mockResolvedValue(response('B'))
    const { loadBootstrap, bootstrapState } = await import('@/stores/bootstrap')
    await expect(loadBootstrap('A')).rejects.toThrow('账号已改变')
    expect(bootstrapState.projects).toEqual([])
  })
})


it('deduplicates startup/page requests and reuses only a recent same-account view', async () => {
  let finish!: (value: unknown) => void
  mocks.bootstrap.mockReturnValue(new Promise((resolve) => { finish = resolve }))
  const { loadBootstrap, bootstrapState, clearBootstrapView } = await import('@/stores/bootstrap')
  const first = loadBootstrap('A')
  const second = loadBootstrap('A')
  expect(mocks.bootstrap).toHaveBeenCalledTimes(1)
  finish(response('A'))
  await Promise.all([first, second])
  expect(bootstrapState.currentProject?.id).toBe('A:project')
  await loadBootstrap('A', '', () => true, 30_000)
  expect(mocks.bootstrap).toHaveBeenCalledTimes(1)
  clearBootstrapView()
  mocks.bootstrap.mockResolvedValue(response('B'))
  await loadBootstrap('B', '', () => true, 30_000)
  expect(mocks.bootstrap).toHaveBeenCalledTimes(2)
  expect(bootstrapState.currentProject?.id).toBe('B:project')
})
