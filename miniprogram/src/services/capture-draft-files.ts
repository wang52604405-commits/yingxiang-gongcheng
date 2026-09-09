/** Draft originals are copied once, then moved into the queue after its recovery WAL exists. */
interface CaptureOriginal {
  originalPath: string
  originalSize: number
  originalFilename: string
}
interface CaptureManifest extends CaptureOriginal { owner: string; project: string; version: 1 }

function token(value: string): string {
  return Array.from(value).map((c) => c.codePointAt(0)!.toString(16).padStart(6, '0')).join('') || 'empty'
}
function api(): { fs: any; root: string } {
  const wxApi = (globalThis as { wx?: any }).wx
  const root = String(wxApi?.env?.USER_DATA_PATH || '').replace(/\/$/, '')
  const fs = wxApi?.getFileSystemManager?.()
  if (!root || !fs?.copyFile || !fs?.statSync || !fs?.writeFileSync) throw new Error('当前环境无法安全保存照片草稿')
  return { fs, root }
}
function directory(root: string, owner: string, project: string): string {
  return `${root}/engineering-image-capture-v1/${token(owner)}/${token(project)}`
}
function readManifest(path: string, owner: string, project: string): CaptureManifest | null {
  try {
    const { fs, root } = api()
    const prefix = `${directory(root, owner, project)}/`
    if (!path.startsWith(prefix) || !/^[A-Za-z0-9_-]+\.(jpg|png|bin)$/.test(path.slice(prefix.length))) return null
    const value = JSON.parse(fs.readFileSync(`${path}.json`, 'utf8')) as CaptureManifest
    if (value.version !== 1 || value.owner !== owner || value.project !== project || value.originalPath !== path) return null
    return value
  } catch { return null }
}

export function captureOriginalFilename(path: string, owner: string, project: string): string | undefined {
  return readManifest(path, owner, project)?.originalFilename
}

/** Recover copies saved just before the page's draft snapshot was interrupted. */
export function listCaptureOriginals(owner: string, project: string): CaptureOriginal[] {
  if (!owner || !project) return []
  try {
    const { fs, root } = api()
    const dir = directory(root, owner, project)
    const names = fs.readdirSync(dir) as string[]
    const recovered: CaptureOriginal[] = []
    for (const name of names) {
      if (!/^[A-Za-z0-9_-]+\.(jpg|png|bin)\.json$/.test(name)) continue
      const path = `${dir}/${name.slice(0, -5)}`
      const manifest = readManifest(path, owner, project)
      if (!manifest || !Number.isFinite(manifest.originalSize) || manifest.originalSize <= 0) continue
      try {
        const stat = fs.statSync(path)
        if (!(stat?.isFile?.() ?? true) || Number(stat?.size) !== manifest.originalSize) continue
        recovered.push({ originalPath: path, originalSize: manifest.originalSize, originalFilename: manifest.originalFilename })
      } catch { /* A pending copy or adopted file is not a recoverable draft. */ }
    }
    return recovered
  } catch { return [] }
}

export async function persistCaptureOriginal(sourcePath: string, owner: string, project: string): Promise<CaptureOriginal> {
  if (!owner || !project) throw new Error('请先选择账号和工程')
  const { fs, root } = api()
  const existing = readManifest(sourcePath, owner, project)
  if (existing && Number(fs.statSync(sourcePath)?.size) === existing.originalSize) return existing
  const originalFilename = sourcePath.replace(/\\/g, '/').split('/').pop() || 'photo'
  const suffix = /\.png$/i.test(originalFilename) ? 'png' : /\.jpe?g$/i.test(originalFilename) ? 'jpg' : 'bin'
  const dir = directory(root, owner, project)
  try { fs.mkdirSync(dir, true) } catch (error) {
    if (!String((error as any)?.errMsg || error).includes('exist')) throw error
  }
  const originalPath = `${dir}/${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}.${suffix}`
  const originalSize = Number(fs.statSync(sourcePath)?.size)
  if (!Number.isFinite(originalSize) || originalSize <= 0) throw new Error('无法确认照片文件大小')
  const manifest: CaptureManifest = { version: 1, owner, project, originalPath, originalSize, originalFilename }
  // Metadata first: even a crash just after copying leaves an identifiable draft.
  fs.writeFileSync(`${originalPath}.json`, JSON.stringify(manifest), 'utf8')
  await new Promise<void>((resolve, reject) => fs.copyFile({ srcPath: sourcePath, destPath: originalPath, success: () => resolve(), fail: reject }))
  if (Number(fs.statSync(originalPath)?.size) !== originalSize) throw new Error('照片草稿大小校验失败，原文件已保留')
  return { originalPath, originalSize, originalFilename }
}

/** Called only after the queue has written its WAL. Unknown paths always fall back to copying. */
export async function adoptCaptureOriginal(sourcePath: string, owner: string, project: string, destinationPath: string, expectedSize: number): Promise<boolean> {
  const manifest = readManifest(sourcePath, owner, project)
  if (!manifest || manifest.originalSize !== expectedSize) return false
  const { fs } = api()
  if (!fs.rename || Number(fs.statSync(sourcePath)?.size) !== expectedSize) return false
  await new Promise<void>((resolve, reject) => fs.rename({ oldPath: sourcePath, newPath: destinationPath, success: () => resolve(), fail: reject }))
  try { fs.unlinkSync(`${sourcePath}.json`) } catch { /* No original remains at the old draft path. */ }
  return true
}

/** Explicit user draft removal only. Never sweeps queue files, other accounts, or unknown paths. */
export async function discardCaptureOriginal(path: string, owner: string, project: string): Promise<boolean> {
  if (!readManifest(path, owner, project)) return false
  const { fs } = api()
  try { fs.unlinkSync(path) } catch { return false }
  try { fs.unlinkSync(`${path}.json`) } catch { /* Original has already been removed explicitly. */ }
  return true
}
