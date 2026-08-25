import type { LocalBatch, LocalPhoto } from '@/types/domain'

const LEGACY_QUEUE_KEY = 'engineering-image:queue:v2'
const VAULT_DIR = 'engineering-image-queue-v3'
const FALLBACK_QUEUE_KEY = 'engineering-image:queue:v3'

interface QueueSnapshot {
  owner_account_id: string
  photos: LocalPhoto[]
  batches: LocalBatch[]
}

interface RecordEnvelope<T> {
  sequence: number
  value: T
}

interface OriginalWal {
  version: 1
  owner_account_id: string
  photo_uuid: string
  original_size: number
  original_path: string
  photo: LocalPhoto
  batch: LocalBatch
}

export interface StagedOriginal {
  originalPath: string
  originalSize: number
  originalFilename: string
}

export interface QueueFileStore {
  load(owner: string): QueueSnapshot
  persistSnapshot(owner: string, photos: LocalPhoto[], batches: LocalBatch[]): void
  stageOriginal(owner: string, batch: LocalBatch, photo: LocalPhoto, sourcePath: string, sourceSize: number): Promise<StagedOriginal>
  clearOriginalWal(owner: string, photoUuid: string): void
}

const sequenceByRecord = new Map<string, number>()

function ownerToken(owner: string): string {
  return Array.from(owner).map((character) => character.codePointAt(0)!.toString(16).padStart(6, '0')).join('') || 'empty'
}

function safeId(value: string): string {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error('本地影像标识不安全')
  return value
}

function userRoot(): string {
  const wxApi = (globalThis as { wx?: any }).wx
  return String(wxApi?.env?.USER_DATA_PATH || '')
}

function fsManager(): any | null {
  const wxApi = (globalThis as { wx?: any }).wx
  const fs = wxApi?.getFileSystemManager?.()
  return fs?.writeFileSync && fs?.readFileSync && fs?.readdirSync && fs?.mkdirSync && fs?.statSync ? fs : null
}

function join(...parts: string[]): string {
  return parts.map((part, index) => index ? part.replace(/^[/\\]+|[/\\]+$/g, '') : part.replace(/[/\\]+$/g, '')).join('/')
}

function accountRoot(owner: string): string {
  return join(userRoot(), VAULT_DIR, 'accounts', ownerToken(owner))
}

function directory(owner: string, kind: 'photos' | 'batches' | 'wal' | 'originals'): string {
  return join(accountRoot(owner), kind)
}

function ensureDirectories(fs: any, owner: string): void {
  for (const path of [accountRoot(owner), directory(owner, 'photos'), directory(owner, 'batches'), directory(owner, 'wal'), directory(owner, 'originals')]) {
    try { fs.mkdirSync(path, true) } catch (error) {
      if (!String((error as { errMsg?: string })?.errMsg || error).includes('exist')) throw error
    }
  }
}

function readText(fs: any, path: string): string {
  const value = fs.readFileSync(path, 'utf8')
  if (typeof value === 'string') return value
  return Array.from(new Uint8Array(value), (byte) => String.fromCharCode(byte)).join('')
}

function readJson<T>(fs: any, path: string): T | null {
  try { return JSON.parse(readText(fs, path)) as T } catch { return null }
}

function list(fs: any, path: string): string[] {
  try { return fs.readdirSync(path) as string[] } catch { return [] }
}

function recordKey(owner: string, kind: string, id: string): string {
  return `${ownerToken(owner)}:${kind}:${id}`
}

function loadRecords<T extends { owner_account_id: string }>(fs: any, owner: string, kind: 'photos' | 'batches'): T[] {
  const records = new Map<string, RecordEnvelope<T>>()
  for (const filename of list(fs, directory(owner, kind))) {
    const match = filename.match(/^([A-Za-z0-9_-]+)\.([01])\.json$/)
    if (!match) continue
    const envelope = readJson<RecordEnvelope<T>>(fs, join(directory(owner, kind), filename))
    if (!envelope || String(envelope.value?.owner_account_id) !== owner || !Number.isInteger(envelope.sequence)) continue
    const previous = records.get(match[1])
    if (!previous || envelope.sequence > previous.sequence) records.set(match[1], envelope)
  }
  for (const [id, envelope] of records) sequenceByRecord.set(recordKey(owner, kind, id), envelope.sequence)
  return [...records.values()].map((record) => record.value)
}

function writeRecord<T>(fs: any, owner: string, kind: 'photos' | 'batches', id: string, value: T): void {
  const key = recordKey(owner, kind, safeId(id))
  const sequence = (sequenceByRecord.get(key) || 0) + 1
  const slot = sequence % 2
  const path = join(directory(owner, kind), `${id}.${slot}.json`)
  fs.writeFileSync(path, JSON.stringify({ sequence, value } satisfies RecordEnvelope<T>), 'utf8')
  sequenceByRecord.set(key, sequence)
}

function pathExistsWithSize(fs: any, path: string, expectedSize: number): boolean {
  try {
    const stats = fs.statSync(path)
    return Boolean(stats?.isFile?.() ?? true) && Number(stats?.size) === expectedSize
  } catch { return false }
}

function legacySnapshot(owner: string): QueueSnapshot {
  try {
    const value = uni.getStorageSync(`${LEGACY_QUEUE_KEY}:account:${owner}`) as QueueSnapshot | null
    if (value?.owner_account_id === owner) return value
  } catch { /* 文件分片是微信端权威来源。 */ }
  return { owner_account_id: owner, photos: [], batches: [] }
}

function fallbackKey(owner: string, kind: 'photos' | 'batches', id?: string): string {
  return `${FALLBACK_QUEUE_KEY}:account:${ownerToken(owner)}:${kind}${id ? `:${id}` : ':index'}`
}

function fallbackSnapshot(owner: string): QueueSnapshot {
  try {
    const photoIds = uni.getStorageSync(fallbackKey(owner, 'photos')) as string[] | null
    const batchIds = uni.getStorageSync(fallbackKey(owner, 'batches')) as string[] | null
    const photos = Array.isArray(photoIds)
      ? photoIds.map((id) => uni.getStorageSync(fallbackKey(owner, 'photos', id)) as LocalPhoto | null).filter((value): value is LocalPhoto => Boolean(value && String(value.owner_account_id) === owner))
      : []
    const batches = Array.isArray(batchIds)
      ? batchIds.map((id) => uni.getStorageSync(fallbackKey(owner, 'batches', id)) as LocalBatch | null).filter((value): value is LocalBatch => Boolean(value && String(value.owner_account_id) === owner))
      : []
    if (photos.length || batches.length) return { owner_account_id: owner, photos, batches }
  } catch { /* 继续尝试只读迁移旧队列。 */ }
  return legacySnapshot(owner)
}

function persistFallback(owner: string, photos: LocalPhoto[], batches: LocalBatch[]): void {
  const ownedPhotos = photos.filter((photo) => String(photo.owner_account_id) === owner)
  const ownedBatches = batches.filter((batch) => String(batch.owner_account_id) === owner)
  for (const batch of ownedBatches) uni.setStorageSync(fallbackKey(owner, 'batches', safeId(batch.client_batch_id)), batch)
  for (const photo of ownedPhotos) uni.setStorageSync(fallbackKey(owner, 'photos', safeId(photo.photo_uuid)), photo)
  uni.setStorageSync(fallbackKey(owner, 'batches'), ownedBatches.map((batch) => batch.client_batch_id))
  uni.setStorageSync(fallbackKey(owner, 'photos'), ownedPhotos.map((photo) => photo.photo_uuid))
}

function recoverWal(fs: any, owner: string, photos: LocalPhoto[], batches: LocalBatch[]): void {
  const photoIds = new Set(photos.map((photo) => photo.photo_uuid))
  const batchIds = new Set(batches.map((batch) => batch.client_batch_id))
  for (const filename of list(fs, directory(owner, 'wal'))) {
    if (!filename.endsWith('.json')) continue
    const wal = readJson<OriginalWal>(fs, join(directory(owner, 'wal'), filename))
    if (!wal || wal.version !== 1 || wal.owner_account_id !== owner || wal.photo.owner_account_id !== owner || wal.batch.owner_account_id !== owner) continue
    if (!pathExistsWithSize(fs, wal.original_path, wal.original_size)) continue
    if (!batchIds.has(wal.batch.client_batch_id)) {
      batches.unshift(wal.batch)
      batchIds.add(wal.batch.client_batch_id)
    }
    const batch = batches.find((item) => item.client_batch_id === wal.batch.client_batch_id)!
    if (!batch.photo_uuids.includes(wal.photo_uuid)) batch.photo_uuids.push(wal.photo_uuid)
    if (!photoIds.has(wal.photo_uuid)) {
      photos.unshift({
        ...wal.photo,
        original_path: wal.original_path,
        original_size: wal.original_size,
        status: 'failed',
        retry_from: 'local_ready',
        retryable: true,
        preparation_pending: true,
        error: '检测到上次处理中断；原图已安全恢复，请继续生成预览',
        progress: 0,
      })
      photoIds.add(wal.photo_uuid)
    }
  }
}

function load(owner: string): QueueSnapshot {
  const fs = fsManager()
  if (!fs || !userRoot()) return fallbackSnapshot(owner)
  ensureDirectories(fs, owner)
  const photos = loadRecords<LocalPhoto>(fs, owner, 'photos')
  const batches = loadRecords<LocalBatch>(fs, owner, 'batches')
  if (!photos.length && !batches.length) {
    const legacy = legacySnapshot(owner)
    photos.push(...legacy.photos.filter((photo) => String(photo.owner_account_id) === owner))
    batches.push(...legacy.batches.filter((batch) => String(batch.owner_account_id) === owner))
  }
  recoverWal(fs, owner, photos, batches)
  return { owner_account_id: owner, photos, batches }
}

function persistSnapshot(owner: string, photos: LocalPhoto[], batches: LocalBatch[]): void {
  const fs = fsManager()
  if (!fs || !userRoot()) {
    // 非微信端也按照片/批次拆键；旧单键只读迁移，永不再写。
    persistFallback(owner, photos, batches)
    return
  }
  ensureDirectories(fs, owner)
  for (const batch of batches.filter((item) => String(item.owner_account_id) === owner)) writeRecord(fs, owner, 'batches', batch.client_batch_id, batch)
  for (const photo of photos.filter((item) => String(item.owner_account_id) === owner)) writeRecord(fs, owner, 'photos', photo.photo_uuid, photo)
}

function sourceFilename(sourcePath: string): string {
  return sourcePath.replace(/\\/g, '/').split('/').pop() || 'photo'
}

function extension(filename: string): string {
  if (/\.png$/i.test(filename)) return '.png'
  if (/\.jpe?g$/i.test(filename)) return '.jpg'
  return '.bin'
}

function copyFile(fs: any, sourcePath: string, destinationPath: string): Promise<void> {
  if (!fs.copyFile) return Promise.reject(new Error('当前微信基础库不支持安全复制原图，请升级微信后重试'))
  return new Promise((resolve, reject) => fs.copyFile({ srcPath: sourcePath, destPath: destinationPath, success: () => resolve(), fail: reject }))
}

async function stageOriginal(owner: string, batch: LocalBatch, photo: LocalPhoto, sourcePath: string, sourceSize: number): Promise<StagedOriginal> {
  const fs = fsManager()
  if (!fs || !userRoot()) throw new Error('当前环境无法安全保存原图')
  if (photo.owner_account_id !== owner || batch.owner_account_id !== owner) throw new Error('照片账号与当前账号不一致')
  ensureDirectories(fs, owner)
  const filename = sourceFilename(sourcePath)
  const originalPath = join(directory(owner, 'originals'), `${safeId(photo.photo_uuid)}${extension(filename)}`)
  const wal: OriginalWal = {
    version: 1,
    owner_account_id: owner,
    photo_uuid: photo.photo_uuid,
    original_size: sourceSize,
    original_path: originalPath,
    photo: { ...photo, original_path: originalPath, original_size: sourceSize, original_filename: filename },
    batch: JSON.parse(JSON.stringify(batch)),
  }
  // 写前清单成功后才允许复制；写入失败时用户临时原图仍未被移动。
  fs.writeFileSync(join(directory(owner, 'wal'), `${safeId(photo.photo_uuid)}.json`), JSON.stringify(wal), 'utf8')
  await copyFile(fs, sourcePath, originalPath)
  let actualSize = 0
  try {
    const stats = fs.statSync(originalPath)
    actualSize = Number(stats?.size || 0)
  } catch {
    const error = new Error('原图已复制，但大小复核失败；重启后会从写前清单恢复') as Error & Partial<StagedOriginal>
    error.originalPath = originalPath
    error.originalSize = sourceSize
    error.originalFilename = filename
    throw error
  }
  if (actualSize !== sourceSize) {
    const error = new Error('原图复制后大小校验失败；已保留恢复清单，请重新进入后处理') as Error & Partial<StagedOriginal>
    error.originalPath = originalPath
    error.originalSize = actualSize
    error.originalFilename = filename
    throw error
  }
  return { originalPath, originalSize: actualSize, originalFilename: filename }
}

function clearOriginalWal(owner: string, photoUuid: string): void {
  const fs = fsManager()
  if (!fs || !userRoot()) return
  try { fs.unlinkSync(join(directory(owner, 'wal'), `${safeId(photoUuid)}.json`)) } catch { /* 下次启动会忽略已无原图的清单。 */ }
}

export const queueFileStore: QueueFileStore = { load, persistSnapshot, stageOriginal, clearOriginalWal }
