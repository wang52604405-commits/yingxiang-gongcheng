import { describe, expect, it, vi } from 'vitest'
import { createPhotoLibrary, type LibraryPhotoPage, type LibraryPhotoQuery } from '@/services/photo-library'
import type { CloudPhoto } from '@/types/domain'

function photo(id: number): CloudPhoto { return { photo_uuid: String(id) } as CloudPhoto }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done }); return { promise, resolve } }

describe('全部影像与持续分页', () => {
  it('连续读取全部725张，没有600张上限，计数不被已加载数量替代', async () => {
    const fetch = vi.fn(async (query: LibraryPhotoQuery) => {
      const offset = Number(query.cursor || 0)
      return { photos: Array.from({ length: Math.min(60, 725 - offset) }, (_, index) => photo(offset + index)), total: 725, next_cursor: offset + 60 < 725 ? String(offset + 60) : '' }
    })
    const library = createPhotoLibrary(() => ({ owner: 'A', query: { project_id: 'A:P' } }), fetch)
    await library.load()
    expect(library.state.totalCount).toBe(725)
    expect(library.state.photos).toHaveLength(60)
    while (library.state.nextCursor) await library.load(false)
    expect(library.state.photos).toHaveLength(725)
    expect(fetch).toHaveBeenCalledTimes(13)
    expect(fetch.mock.calls[0][0]).not.toHaveProperty('scope')
    expect(fetch.mock.calls[0][0]).not.toHaveProperty('category')
  })

  it('旧账号或项目的在途照片不会进入新列表，未选项目也使旧请求失效', async () => {
    const oldPage = deferred<LibraryPhotoPage>()
    let context = { owner: 'A', query: { project_id: 'A:P' } }
    const fetch = vi.fn().mockReturnValueOnce(oldPage.promise).mockResolvedValueOnce({ photos: [photo(200)], total: 1, next_cursor: '' })
    const library = createPhotoLibrary(() => context, fetch)
    const pending = library.load()
    context = { owner: 'B', query: { project_id: 'B:Q' } }
    await library.load()
    oldPage.resolve({ photos: [photo(100)], total: 600, next_cursor: 'old' })
    await pending
    expect(library.state.photos.map((item) => item.photo_uuid)).toEqual(['200'])
    expect(library.state.totalCount).toBe(1)
    context = { owner: 'B', query: { project_id: '' } }
    await library.load()
    expect(library.state.photos).toEqual([])
    expect(library.state.totalCount).toBe(0)
  })

  it('切换筛选时忽略旧翻页，并阻止重复加载同一页', async () => {
    let query: LibraryPhotoQuery = { project_id: 'A:P', scope: 'engineering' }
    const oldMore = deferred<LibraryPhotoPage>()
    const fetch = vi.fn().mockResolvedValueOnce({ photos: [photo(1)], total: 602, next_cursor: 'page2' })
      .mockReturnValueOnce(oldMore.promise).mockResolvedValueOnce({ photos: [photo(900)], total: 1, next_cursor: '' })
    const library = createPhotoLibrary(() => ({ owner: 'A', query }), fetch)
    await library.load()
    const pending = library.load(false)
    await library.load(false)
    expect(fetch).toHaveBeenCalledTimes(2)
    query = { project_id: 'A:P', scope: 'other', other_node_code: 'QT-1' }
    await library.load()
    oldMore.resolve({ photos: [photo(2)], total: 602, next_cursor: 'page3' })
    await pending
    expect(library.state.photos.map((item) => item.photo_uuid)).toEqual(['900'])
    expect(library.state.totalCount).toBe(1)
    expect(library.state.loadingMore).toBe(false)
  })

  it('账号改变但页面尚未重新加载时，也不接收原账号响应', async () => {
    const waiting = deferred<LibraryPhotoPage>()
    let owner = 'A'
    const library = createPhotoLibrary(() => ({ owner, query: { project_id: 'shared' } }), () => waiting.promise)
    const pending = library.load()
    owner = 'B'
    waiting.resolve({ photos: [photo(1)], total: 1, next_cursor: '' })
    await pending
    expect(library.state.photos).toEqual([])
  })
})
