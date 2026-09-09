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
  async function load(reset = true): Promise<void> {
    const current = snapshot()
    const key = JSON.stringify(current)
    if (key !== activeKey) reset = true
    if (!reset && (state.loading || state.loadingMore || !state.nextCursor)) return
    if (reset) {
      version += 1
      activeKey = key
      state.photos = []
      state.totalCount = 0
      state.nextCursor = ''
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
      const existing = new Set(state.photos.map((photo) => photo.photo_uuid))
      for (const photo of response.photos) {
        if (existing.has(photo.photo_uuid)) continue
        state.photos.push(photo)
        existing.add(photo.photo_uuid)
      }
      state.nextCursor = response.next_cursor || ''
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
  return { state, load }
}
