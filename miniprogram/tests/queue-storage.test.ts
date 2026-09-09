import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LocalBatch, LocalPhoto, UploadDraft } from '@/types/domain'

const draft: UploadDraft = {
  project_id: 'YNLQ',
  scope: 'engineering',
  category: 'construction',
  mode: 'direct',
  assignment: { unit_code: 'YNLQ-DY-001', unit_name: '进口段' },
}

class MemoryFs {
  readonly files = new Map<string, string | ArrayBuffer>()
  readonly directories = new Set<string>()
  failWrite: ((path: string) => boolean) | null = null
  copies = 0
  moves = 0
  writes = 0

  mkdirSync(path: string) { this.directories.add(path) }
  writeFileSync(path: string, data: string | ArrayBuffer) {
    if (this.failWrite?.(path)) throw new Error('storage quota exceeded')
    this.writes += 1
    this.files.set(path, data)
  }
  readFileSync(path: string) {
    if (!this.files.has(path)) throw new Error('not found')
    return this.files.get(path)!
  }
  readdirSync(path: string) {
    const prefix = `${path}/`
    return [...this.files.keys()]
      .filter((file) => file.startsWith(prefix) && !file.slice(prefix.length).includes('/'))
      .map((file) => file.slice(prefix.length))
  }
  statSync(path: string) {
    if (!this.files.has(path)) throw new Error('not found')
    const value = this.files.get(path)!
    return { size: typeof value === 'string' ? new TextEncoder().encode(value).byteLength : value.byteLength, isFile: () => true }
  }
  copyFile({ srcPath, destPath, success, fail }: any) {
    this.copies += 1
    const source = this.files.get(srcPath)
    if (source === undefined) { fail(new Error('source missing')); return }
    this.files.set(destPath, source instanceof ArrayBuffer ? source.slice(0) : source)
    success({})
  }
  rename({ oldPath, newPath, success, fail }: any) {
    const source = this.files.get(oldPath)
    if (source === undefined) { fail(new Error('source missing')); return }
    this.moves += 1
    this.files.set(newPath, source)
    this.files.delete(oldPath)
    success({})
  }
  unlinkSync(path: string) { this.files.delete(path) }
}

function photo(owner: string, id: string): LocalPhoto {
  const timestamp = '2026-08-25T01:00:00.000Z'
  return {
    owner_account_id: owner,
    photo_uuid: id,
    client_batch_id: `batch-${owner}`,
    original_path: '',
    original_size: 12,
    original_sha256: '',
    original_filename: 'camera.jpg',
    original_mime_type: '',
    preview_path: '',
    preview_size: 0,
    preview_sha256: '',
    preview_width: 0,
    preview_height: 0,
    width: 0,
    height: 0,
    orientation: 1,
    client_captured_at: timestamp,
    title: '现场照片',
    photo_date: '2026-08-25',
    draft,
    status: 'failed',
    retry_from: 'local_ready',
    retryable: true,
    preparation_pending: true,
    progress: 0,
    created_at: timestamp,
    updated_at: timestamp,
  }
}

function batch(owner: string, id: string): LocalBatch {
  return {
    owner_account_id: owner,
    client_batch_id: `batch-${owner}`,
    draft,
    photo_uuids: [id],
    committed: false,
    analyzed: false,
    created_at: '2026-08-25T01:00:00.000Z',
  }
}

describe('账号分片队列与原图写前清单', () => {
  let fs: MemoryFs

  beforeEach(() => {
    vi.resetModules()
    fs = new MemoryFs()
    ;(globalThis as any).wx = { env: { USER_DATA_PATH: '/user' }, getFileSystemManager: () => fs }
    ;(globalThis as any).uni = {
      getStorageSync: vi.fn(() => undefined),
      setStorageSync: vi.fn(() => { throw new Error('localStorage quota exceeded') }),
    }
  })

  it('选图到入队只复制一次；原子移动后立即退出仍通过 WAL 恢复', async () => {
    fs.files.set('/tmp/camera.jpg', new Uint8Array(12).buffer)
    const { persistCaptureOriginal, discardCaptureOriginal } = await import('@/services/capture-draft-files')
    const { queueFileStore } = await import('@/services/queue-storage')
    const saved = await persistCaptureOriginal('/tmp/camera.jpg', 'A', 'YNLQ')
    const item = photo('A', 'adopted')
    const staged = await queueFileStore.stageOriginal('A', batch('A', item.photo_uuid), item, saved.originalPath, 12)
    expect(fs.copies).toBe(1)
    expect(fs.moves).toBe(1)
    expect(staged.originalFilename).toBe('camera.jpg')
    expect(await discardCaptureOriginal(saved.originalPath, 'A', 'YNLQ')).toBe(false)
    expect(fs.files.has(staged.originalPath)).toBe(true)
    expect(queueFileStore.load('A').photos[0].original_path).toBe(staged.originalPath)
  })

  it('WAL 写入失败不会移动草稿，重新提交仍可恢复', async () => {
    fs.files.set('/tmp/camera.jpg', new Uint8Array(12).buffer)
    const { persistCaptureOriginal } = await import('@/services/capture-draft-files')
    const { queueFileStore } = await import('@/services/queue-storage')
    const saved = await persistCaptureOriginal('/tmp/camera.jpg', 'A', 'YNLQ')
    const item = photo('A', 'wal-fails')
    fs.failWrite = (path) => path.includes('/wal/')
    await expect(queueFileStore.stageOriginal('A', batch('A', item.photo_uuid), item, saved.originalPath, 12)).rejects.toThrow('quota')
    expect(fs.files.has(saved.originalPath)).toBe(true)
    expect(fs.moves).toBe(0)
  })

  it('草稿删除严格限定本人当前工程，且不触碰原始相册文件', async () => {
    fs.files.set('/tmp/camera.jpg', new Uint8Array(12).buffer)
    const { persistCaptureOriginal, discardCaptureOriginal } = await import('@/services/capture-draft-files')
    const saved = await persistCaptureOriginal('/tmp/camera.jpg', 'A', 'YNLQ')
    expect(await discardCaptureOriginal(saved.originalPath, 'B', 'YNLQ')).toBe(false)
    expect(await discardCaptureOriginal(saved.originalPath, 'A', 'another')).toBe(false)
    expect(await discardCaptureOriginal('/tmp/camera.jpg', 'A', 'YNLQ')).toBe(false)
    expect(await discardCaptureOriginal(saved.originalPath, 'A', 'YNLQ')).toBe(true)
    expect(fs.files.has('/tmp/camera.jpg')).toBe(true)
  })

  it('页面快照前退出可列出完整草稿，忽略缺失或不完整副本并隔离账号工程', async () => {
    fs.files.set('/tmp/camera.jpg', new Uint8Array(12).buffer)
    const { persistCaptureOriginal, listCaptureOriginals } = await import('@/services/capture-draft-files')
    const complete = await persistCaptureOriginal('/tmp/camera.jpg', 'A', 'YNLQ')
    const missing = await persistCaptureOriginal('/tmp/camera.jpg', 'A', 'YNLQ')
    const incomplete = await persistCaptureOriginal('/tmp/camera.jpg', 'A', 'YNLQ')
    await persistCaptureOriginal('/tmp/camera.jpg', 'B', 'YNLQ')
    await persistCaptureOriginal('/tmp/camera.jpg', 'A', 'another')
    fs.files.delete(missing.originalPath)
    fs.files.set(incomplete.originalPath, new Uint8Array(3).buffer)
    expect(listCaptureOriginals('A', 'YNLQ')).toEqual([complete])
    expect(listCaptureOriginals('B', 'YNLQ')).toHaveLength(1)
    expect(listCaptureOriginals('A', 'another')).toHaveLength(1)
    expect(fs.files.has(`${missing.originalPath}.json`)).toBe(true)
    expect(fs.files.has(incomplete.originalPath)).toBe(true)
  })

  it('500 张历史照片只写变化的那一张，断点失败仍可原样重试落盘', async () => {
    const { queueFileStore } = await import('@/services/queue-storage')
    const photos = Array.from({ length: 500 }, (_, index) => photo('A', `history-${index}`))
    const group = batch('A', 'history-0')
    queueFileStore.persistSnapshot('A', photos, [group])
    expect(fs.writes).toBe(501)
    photos[0].progress = 20
    queueFileStore.persistSnapshot('A', photos, [group])
    expect(fs.writes).toBe(502)
    queueFileStore.persistSnapshot('A', photos, [group])
    expect(fs.writes).toBe(502)
    photos[0].uploaded_chunks = [0]
    fs.failWrite = (path) => path.includes('/photos/history-0.')
    expect(() => queueFileStore.persistSnapshot('A', photos, [group])).toThrow('quota')
    fs.failWrite = null
    queueFileStore.persistSnapshot('A', photos, [group])
    expect(fs.writes).toBe(503)
    expect(queueFileStore.load('A').photos.find((entry) => entry.photo_uuid === 'history-0')?.uploaded_chunks).toEqual([0])
  })

  it('原图复制成功后即使进程在照片分片写入前退出，重启也从 WAL 精确恢复', async () => {
    fs.files.set('/tmp/camera.jpg', new Uint8Array(12).buffer)
    const { queueFileStore } = await import('@/services/queue-storage')
    const item = photo('32', 'photo-crash')
    const group = batch('32', item.photo_uuid)
    const staged = await queueFileStore.stageOriginal('32', group, item, '/tmp/camera.jpg', 12)

    expect(staged.originalPath).toContain('/accounts/000033000032/originals/photo-crash.jpg')
    // 不调用 persistSnapshot，精确模拟 copyFile success 后立即杀进程。
    const recovered = queueFileStore.load('32')
    expect(recovered.batches[0].photo_uuids).toEqual(['photo-crash'])
    expect(recovered.photos[0]).toMatchObject({
      owner_account_id: '32',
      photo_uuid: 'photo-crash',
      original_path: staged.originalPath,
      preparation_pending: true,
      status: 'failed',
    })
  })

  it('照片元数据遇到文件配额失败时，已落盘原图仍由 WAL 跟踪并可恢复', async () => {
    fs.files.set('/tmp/quota.jpg', new Uint8Array(12).buffer)
    const { queueFileStore } = await import('@/services/queue-storage')
    const item = photo('quota-owner', 'photo-quota')
    const group = batch('quota-owner', item.photo_uuid)
    const staged = await queueFileStore.stageOriginal('quota-owner', group, item, '/tmp/quota.jpg', 12)
    item.original_path = staged.originalPath
    fs.failWrite = (path) => path.includes('/photos/')

    expect(() => queueFileStore.persistSnapshot('quota-owner', [item], [group])).toThrow('quota')
    fs.failWrite = null
    const recovered = queueFileStore.load('quota-owner')
    expect(recovered.photos.map((entry) => entry.photo_uuid)).toEqual(['photo-quota'])
    expect((globalThis as any).uni.setStorageSync).not.toHaveBeenCalled()
  })

  it('只扫描当前账号目录，另一账号的 WAL 和原图绝不会出现在新账号队列', async () => {
    fs.files.set('/tmp/account-a.jpg', new Uint8Array(12).buffer)
    const { queueFileStore } = await import('@/services/queue-storage')
    const item = photo('A', 'photo-a')
    await queueFileStore.stageOriginal('A', batch('A', item.photo_uuid), item, '/tmp/account-a.jpg', 12)

    expect(queueFileStore.load('B')).toEqual({ owner_account_id: 'B', photos: [], batches: [] })
    expect(queueFileStore.load('A').photos[0].photo_uuid).toBe('photo-a')
  })

  it('双槽分片写入失败时保留上一份完整状态，不读取半写 JSON', async () => {
    const { queueFileStore } = await import('@/services/queue-storage')
    const item = photo('slots', 'photo-slots')
    item.upload_mode = 'chunked'
    item.chunk_upload_id = 'upload-slots'
    item.upload_chunk_size = 4 * 1024 * 1024
    item.upload_total_chunks = 3
    item.uploaded_chunks = [0, 1]
    const group = batch('slots', item.photo_uuid)
    queueFileStore.persistSnapshot('slots', [item], [group])
    item.status = 'uploading'
    fs.failWrite = (path) => path.includes('/photos/photo-slots.0.json')
    expect(() => queueFileStore.persistSnapshot('slots', [item], [group])).toThrow('quota')
    fs.failWrite = null

    expect(queueFileStore.load('slots').photos[0]).toMatchObject({
      status: 'failed',
      chunk_upload_id: 'upload-slots',
      uploaded_chunks: [0, 1],
    })
  })
})
