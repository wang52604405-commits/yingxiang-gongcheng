import { reactive } from 'vue'
import type { CloudPhoto } from '@/types/domain'

export interface LibraryPhotoQuery {
  project_id: string
  scope?: string
  category?: string
  unit_code?: string
  other_node_code?: string
  cursor?: string
  limit?: number
}
export interface LibraryPhotoPage { photos: CloudPhoto[]; total: number; next_cursor: string }

/** One paging session per account, project and filter; old responses never cross sessions. */
export function createPhotoLibrary(
  snapshot: () => { owner: string; query: LibraryPhotoQuery },
  fetchPage: (query: LibraryPhotoQuery) => Promise<LibraryPhotoPage>,
) {
  const state = reactive({ photos: [] as CloudPhoto[], totalCount: 0, nextCursor: '', loading: false, loadingMore: false, error: '' })
  let version = 0
  let activeKey = ''
  let refreshedAt = 0
  async function load(reset = true): Promise<void> {
    const current = snapshot()
    const key = JSON.stringify(current)
    const contextChanged = key !== activeKey
    if (contextChanged) reset = true
    if (!contextChanged && reset && state.loading) return
    if (!reset && (state.loading || state.loadingMore || !state.nextCursor)) return
    if (reset) {
      version += 1
      activeKey = key
      // Keep mounted images during a refresh. A different account/project/filter
      // must clear immediately so previous project photos never leak into it.
      if (contextChanged) {
        state.photos = []
        state.totalCount = 0
        state.nextCursor = ''
        refreshedAt = 0
      }
      state.loadingMore = false
      state.error = ''
    }
    const requestVersion = version
    const stillCurrent = () => requestVersion === version && JSON.stringify(snapshot()) === key
    if (!current.query.project_id) { state.loading = false; return }
    if (reset) state.loading = true
    else state.loadingMore = true
    state.error = ''
    try {
      const cursor = reset ? undefined : state.nextCursor
      const response = await fetchPage({ ...current.query, cursor, limit: 60 })
      if (!stillCurrent()) return
      const unchangedHead = reset && response.total === state.totalCount
        && response.photos.length > 0
        && response.photos.every((photo, index) => state.photos[index]?.photo_uuid === photo.photo_uuid)
      const savedCursor = state.nextCursor
      if (reset) {
        const previous = new Map(state.photos.map((photo) => [photo.photo_uuid, photo]))
        const incoming = response.photos.map((photo) => {
          const old = previous.get(photo.photo_uuid)
          return old && JSON.stringify(old) === JSON.stringify(photo) ? old : photo
        })
        state.photos = unchangedHead ? [...incoming, ...state.photos.slice(incoming.length)] : incoming
      }
      const existing = new Set(state.photos.map((photo) => photo.photo_uuid))
      for (const photo of response.photos) {
        if (existing.has(photo.photo_uuid)) continue
        state.photos.push(photo)
        existing.add(photo.photo_uuid)
      }
      state.nextCursor = unchangedHead ? savedCursor : response.next_cursor || ''
      refreshedAt = Date.now()
      state.totalCount = response.total
      if (cursor && cursor === state.nextCursor) {
        state.nextCursor = ''
        state.error = '照片分页未更新，请下拉刷新后重试'
      }
    } catch (error) {
      if (stillCurrent()) state.error = error instanceof Error ? error.message : '影像加载失败，请重试'
    } finally {
      if (stillCurrent()) { state.loading = false; state.loadingMore = false }
    }
  }
  async function refreshIfStale(maxAgeMs = 30_000): Promise<void> {
    if (JSON.stringify(snapshot()) === activeKey && refreshedAt && Date.now() - refreshedAt < maxAgeMs) return
    await load(true)
  }
  return { state, load, refreshIfStale }
}
