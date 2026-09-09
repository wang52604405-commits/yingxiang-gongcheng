import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { transpileModule } from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const source = readFileSync(resolve('src/pages/upload/index.vue'), 'utf8')
const removalCode = source.slice(source.indexOf('async function removeCandidates('), source.indexOf('function openWatermark('))
function harness() {
  const items = { value: ['a', 'b', 'c'].map(path => ({ path: `/draft/${path}`, sourcePath: `/album/${path}` })) }
  const selected = { value: [1, 2] }
  const scopeOwner = { value: 'owner' }, scopeProject = { value: 'project' }
  const choosing = { value: false }, submitting = { value: false }, draftWarning = { value: '' }
  const discard = vi.fn(async () => true), persist = vi.fn()
  const storage = { getOwner: () => 'owner', getProject: () => ({ id: 'project' }) }
  const env = { items, selected, scopeOwner, scopeProject, choosing, submitting, draftWarning, discardCaptureOriginal: discard, persistDraft: persist, selectionStorage: storage, uni: { showModal: vi.fn() } }
  const compiled = transpileModule(removalCode, { compilerOptions: { target: 9 } }).outputText
  const methods = new Function(...Object.keys(env), `${compiled}; return { removeCandidates, removePhoto, removeSelected };`)(...Object.values(env))
  return { ...env, ...methods, discard, persist }
}

describe('候选照片移除', () => {
  it('移除只清理草稿副本，并按照片保留其余勾选，避免索引错位', async () => {
    const page = harness()
    await page.removeCandidates(['/draft/a', '/draft/b'])
    expect(page.items.value.map((item: { path: string }) => item.path)).toEqual(['/draft/c'])
    expect(page.selected.value).toEqual([0])
    expect(page.discard.mock.calls).toEqual([['/draft/a', 'owner', 'project'], ['/draft/b', 'owner', 'project']])
    expect(page.persist).toHaveBeenCalledOnce()
  })
  it('草稿保存失败时保留可恢复副本；正在提交时不能移除', async () => {
    const page = harness()
    page.draftWarning.value = '保存失败'
    await page.removeCandidates(['/draft/a'])
    expect(page.discard).not.toHaveBeenCalled()
    page.submitting.value = true
    await page.removeCandidates(['/draft/b'])
    expect(page.items.value.map((item: { path: string }) => item.path)).toEqual(['/draft/b', '/draft/c'])
  })
  it('账号切换后旧页不能移除新账号候选', async () => {
    const page = harness()
    page.selectionStorage.getOwner = () => 'another'
    await page.removeCandidates(['/draft/a'])
    expect(page.items.value).toHaveLength(3)
    expect(page.persist).not.toHaveBeenCalled()
    expect(page.discard).not.toHaveBeenCalled()
  })
})
