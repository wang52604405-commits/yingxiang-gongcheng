import { mobileApi } from '@/api/mobile'
import { selectionStorage } from '@/stores/selection'
import type { Scope } from '@/types/domain'

type TreeResponse = Awaited<ReturnType<typeof mobileApi.projectTree>>
type CachedTree = { result?: TreeResponse; expires: number; pending?: Promise<TreeResponse> }
const cache = new Map<string, CachedTree>()
let cacheOwner = ''

/** Brief in-memory reuse between capture and selector; submit can force a live check. */
export function loadDestinationTree(projectId: string, scope: Scope, force = false): Promise<TreeResponse> {
  const owner = selectionStorage.getOwner()
  if (cacheOwner !== owner) { cache.clear(); cacheOwner = owner }
  const key = JSON.stringify([owner, projectId, scope])
  const previous = cache.get(key)
  if (!force && previous?.pending) return previous.pending
  if (!force && previous?.result && previous.expires > Date.now()) return Promise.resolve(previous.result)
  const entry: CachedTree = { expires: 0 }
  const pending = (scope === 'engineering' ? mobileApi.projectTree(projectId) : mobileApi.otherTree(projectId))
    .then((result) => {
      if (selectionStorage.getOwner() !== owner) throw new Error('账号已切换，请重新选择工程部位')
      entry.result = result
      entry.expires = Date.now() + 30_000
      return result
    }).catch((error) => {
      if (cache.get(key) === entry) cache.delete(key)
      throw error
    }).finally(() => { entry.pending = undefined })
  entry.pending = pending
  if (cache.size >= 12) cache.delete(cache.keys().next().value!)
  cache.set(key, entry)
  return pending
}
