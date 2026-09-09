export interface WatermarkLocationText { label: '当前定位' | '拍摄位置' | '手填位置'; text: string }
export interface PhotoWatermarkFields {
  project?: string; companyName?: string; projectName?: string; unitProjectName?: string; partName?: string; unitName?: string
  constructionContent?: string; capturedAt?: string; contractor?: string
  title?: string; sitePart?: string; photographer?: string; photoDate?: string; location?: WatermarkLocationText; note?: string
}
export interface PhotoWatermarkOptions { overlaySize?: { width: number; height: number }; maxEdge?: 2048 | 4096; logoPath?: string; logoCrop?: { x: number; y: number; width: number; height: number }; position?: 'bottom-left' | 'bottom-right'; fontScale?: .85 | 1 | 1.2; opacity?: .55 | .75 | .9 }
export interface WatermarkedPhoto { tempFilePath: string; originalPath: string; width: number; height: number }
export class WatermarkError extends Error {
  constructor(message: string, public code: string, public canOpenSettings = false) { super(message); this.name = 'WatermarkError' }
}

function wechat(): any {
  const api = (globalThis as { wx?: any }).wx
  if (!api) throw new WatermarkError('请在微信小程序内使用此功能', 'UNSUPPORTED')
  return api
}

function callback<T>(run: (success: (value: T) => void, fail: (error: unknown) => void) => void, timeout = 15_000): Promise<T> {
  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (error?: unknown, value?: T) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (error) reject(error); else resolve(value as T)
    }
    const timer = setTimeout(() => finish(new WatermarkError('处理超时，请重试', 'TIMEOUT')), timeout)
    try { run((value) => finish(undefined, value), (error) => finish(error)) } catch (error) { finish(error) }
  })
}

function readableError(error: unknown, kind: 'location' | 'save'): WatermarkError {
  if (error instanceof WatermarkError) return error
  const detail = String((error as any)?.errMsg || (error as any)?.message || error)
  const denied = /deny|denied|auth|authorize|privacy|cancel|permission/i.test(detail)
  return new WatermarkError(denied
    ? kind === 'location' ? '未获得定位授权，可在设置中允许后重试，也可手填位置' : '未获得相册授权，可在设置中允许后重试'
    : kind === 'location' ? '暂时无法取得位置，请重试或手填位置' : '保存失败，请重试',
  denied ? 'PERMISSION_DENIED' : kind === 'location' ? 'LOCATION_FAILED' : 'SAVE_FAILED', denied)
}

/** Invoked only from explicit foreground location/save actions; never opens settings. */
async function authorizedAction<T>(kind: 'location' | 'save', action: (api: any) => Promise<T>): Promise<T> {
  const api = wechat()
  let active = true
  const hide = () => { active = false }
  api.onAppHide?.(hide)
  try {
    if (api.requirePrivacyAuthorize) await callback<void>((success, fail) => api.requirePrivacyAuthorize({ success, fail }), 60_000)
    if (!active) throw new WatermarkError('请返回小程序后重试', 'BACKGROUND')
    const result = await action(api)
    if (!active) throw new WatermarkError('请返回小程序后重试', 'BACKGROUND')
    return result
  } catch (error) { throw readableError(error, kind) }
  finally { api.offAppHide?.(hide) }
}

export async function getCurrentWatermarkLocation() {
  return authorizedAction('location', async (api) => {
    if (!api.getLocation) throw new WatermarkError('当前微信版本不支持定位，请手填位置', 'UNSUPPORTED')
    const value = await callback<any>((success, fail) => api.getLocation({ type: 'gcj02', isHighAccuracy: true, highAccuracyExpireTime: 5000, success, fail }))
    const latitude = Number(value.latitude)
    const longitude = Number(value.longitude)
    if (!Number.isFinite(latitude) || Math.abs(latitude) > 90 || !Number.isFinite(longitude) || Math.abs(longitude) > 180) throw new WatermarkError('定位结果无效，请重新定位', 'LOCATION_FAILED')
    const accuracy = Number.isFinite(Number(value.accuracy)) ? Math.max(0, Number(value.accuracy)) : null
    return { latitude, longitude, accuracy, coordinateSystem: 'gcj02' as const, capturedAt: new Date().toISOString(), label: '当前定位' as const,
      text: `${latitude.toFixed(6)}, ${longitude.toFixed(6)}（GCJ-02${accuracy === null ? '' : `，精度约 ${Math.round(accuracy)} 米`}）` }
  })
}

export async function saveWatermarkToAlbum(tempFilePath: string): Promise<void> {
  if (!tempFilePath || /^https?:\/\//i.test(tempFilePath)) throw new WatermarkError('请先生成水印照片', 'INVALID_PATH')
  return authorizedAction('save', async (api) => {
    if (!api.saveImageToPhotosAlbum) throw new WatermarkError('当前微信版本不支持保存照片', 'UNSUPPORTED')
    await callback<void>((success, fail) => api.saveImageToPhotosAlbum({ filePath: tempFilePath, success, fail }), 60_000)
  })
}

export function watermarkTextRows(fields: PhotoWatermarkFields): string[] {
  const rows: string[] = []
  const add = (label: string, value?: string) => { if (value?.trim()) rows.push(`${label}：${value.trim()}`) }
  add('工程', fields.project)
  add('题名', fields.title)
  add('施工部位', fields.sitePart)
  add('拍摄者', fields.photographer)
  add('拍摄日期', fields.photoDate)
  if (fields.location) add(fields.location.label, fields.location.text)
  if (fields.note?.trim()) fields.note.trim().split(/\r?\n/).forEach((line, index) => { if (line.trim()) rows.push(index === 0 ? `备注：${line.trim()}` : line.trim()) })
  return rows
}

export function wrapWatermarkText(text: string, width: number, measure: (text: string) => number): string[] {
  const lines: string[] = []
  let current = ''
  for (const character of Array.from(text.replace(/[\r\n\t]+/g, ' '))) {
    if (current && measure(current + character) > width) { lines.push(current); current = '' }
    current += character
  }
  if (current) lines.push(current)
  if (lines.length > 1) {
    const last = Array.from(lines[lines.length - 1])
    const previous = Array.from(lines[lines.length - 2])
    if (last.length < 3 && previous.length > 3) {
      const moved = previous.splice(previous.length - (3 - last.length))
      lines[lines.length - 2] = previous.join('')
      lines[lines.length - 1] = [...moved, ...last].join('')
    }
  }
  return lines
}

export function layoutWatermark(width: number, height: number, fields: PhotoWatermarkFields, measureAtSize: (text: string, fontSize: number) => number, options: PhotoWatermarkOptions & { logoSize?: { width: number; height: number } } = {}) {
  if (width < 80 || height < 80) throw new WatermarkError('照片尺寸过小，无法清楚添加水印', 'IMAGE_TOO_SMALL')
  const margin = Math.max(6, Math.round(Math.min(width, height) * .025))
  const maxPanelWidth = width - margin * 2
  const padding = Math.max(5, Math.round(margin * .75))
  const maxWidth = maxPanelWidth - padding * 2
  const fontScale = [.85, 1, 1.2].includes(Number(options.fontScale)) ? Number(options.fontScale) : 1
  let fontSize = Math.max(10, Math.min(78, Math.round(Math.min(width / 32, height / 22) * fontScale)))
  const logoHeight = options.logoSize ? options.logoSize.height + padding : 0
  const rows = watermarkTextRows(fields)
  if (!rows.length && !options.logoSize) throw new WatermarkError('请至少填写一项水印信息', 'EMPTY_WATERMARK')
  let lines: string[] = []
  let lineHeight = 0
  while (true) {
    lines = rows.flatMap((row) => wrapWatermarkText(row, maxWidth, (text) => measureAtSize(text, fontSize)))
    lineHeight = Math.ceil(fontSize * 1.45)
    if (lines.length * lineHeight + padding * 2 + logoHeight <= height - margin * 2) break
    if (fontSize <= 10) throw new WatermarkError('水印内容较多，请缩短题名或位置后重试', 'TEXT_TOO_LONG')
    fontSize -= 1
  }
  const panelHeight = lines.length * lineHeight + padding * 2 + logoHeight
  const panelWidth = Math.min(maxPanelWidth, Math.ceil(Math.max(options.logoSize?.width || 0, ...lines.map((line) => measureAtSize(line, fontSize))) + padding * 2))
  return { x: options.position === 'bottom-right' ? width - margin - panelWidth : margin, y: height - margin - panelHeight, width: panelWidth, height: panelHeight, padding, fontSize, lineHeight, lines, textOffsetY: padding + logoHeight }
}

const ORIENTATIONS: Record<string, number> = { up: 1, 'up-mirrored': 2, down: 3, 'down-mirrored': 4, 'left-mirrored': 5, right: 6, 'right-mirrored': 7, left: 8 }

export function fixedWatermarkRows(fields: PhotoWatermarkFields): string[] {
  const content = fields.constructionContent?.trim() || fields.sitePart?.trim() || fields.title?.trim() || ''
  const construction = [fields.unitName?.trim(), content].filter(Boolean).join('—')
  const location = fields.location?.text?.trim()
  return [
    `单位工程：${fields.unitProjectName?.trim() || '未填写'}`,
    `施工区域：${fields.partName?.trim() || '未填写'}`,
    `施工内容：${construction || '未填写'}`,
    `拍摄者：${fields.photographer?.trim() || '未填写'}`,
    `位置：${location || '未添加位置'}`,
  ]
}

export function layoutFixedWatermark(width: number, height: number, fields: PhotoWatermarkFields, measureAtSize: (text: string, fontSize: number) => number, logoSize?: { width: number; height: number }) {
  if (width < 160 || height < 120) throw new WatermarkError('照片尺寸过小，无法清楚添加水印', 'IMAGE_TOO_SMALL')
  const margin = Math.max(6, Math.round(Math.min(width, height) * .02))
  const panelWidth = Math.min(width - margin * 2, Math.max(160, Math.round(width * (width >= height ? .36 : .44))))
  const targetArea = width * height / 8
  const maxArea = width * height * .16
  const preferredMinFont = Math.max(10, Math.round(Math.min(width, height) / 62))
  let fontSize = Math.max(10, Math.min(54, Math.round(Math.min(width, height) / 38)))
  while (true) {
    const padding = Math.max(5, Math.round(fontSize * .38))
    const gap = Math.max(2, Math.round(fontSize * .1))
    const lineHeight = Math.ceil(fontSize * 1.32)
    const logoBoxWidth = logoSize || fields.companyName ? Math.round(fontSize * 4.8) : 0
    const brandFontSize = fontSize
    const brandLines = fields.companyName ? [fields.companyName] : []
    const brandLineHeight = Math.ceil(brandFontSize * 1.25)
    const brandHeight = brandLines.length * brandLineHeight
    const headerFontSize = fontSize
    const headerLineHeight = Math.ceil(headerFontSize * 1.3)
    const headerWidth = Math.max(fontSize * 5, panelWidth - logoBoxWidth - padding * 2)
    const headerLines = wrapWatermarkText(fields.projectName?.trim() || fields.project?.trim() || '未选择工程', headerWidth, (text) => measureAtSize(text, headerFontSize))
    const logoPreviewHeight = logoSize && logoBoxWidth > padding * 2 ? Math.round(logoSize.height * ((logoBoxWidth - padding * 2) / logoSize.width)) : 0
    const headerTextHeight = headerLines.length * headerLineHeight + padding * 2
    const headerLogoHeight = logoBoxWidth ? logoPreviewHeight + brandHeight + padding * 3 : 0
    const headerHeight = Math.max(headerTextHeight, headerLogoHeight, lineHeight + padding * 2)
    const logoScale = logoSize ? Math.max(0, Math.min((logoBoxWidth - padding * 2) / logoSize.width, Math.max(1, headerHeight - padding * 3 - brandHeight) / logoSize.height)) : 0
    const logo = logoSize ? { width: Math.max(1, Math.round(logoSize.width * logoScale)), height: Math.max(1, Math.round(logoSize.height * logoScale)) } : undefined
    const bodyLines = fixedWatermarkRows(fields).flatMap((row) => wrapWatermarkText(row, panelWidth - padding * 2, (text) => measureAtSize(text, fontSize)))
    const bodyHeight = bodyLines.length * lineHeight + padding * 2
    const footerLines = wrapWatermarkText(`施工单位：${fields.contractor?.trim() || '未填写'}`, panelWidth - padding * 2, (text) => measureAtSize(text, fontSize))
    const footerHeight = footerLines.length * lineHeight + padding * 2
    const panelHeight = headerHeight + bodyHeight + footerHeight + gap * 2
    const area = panelWidth * panelHeight
    if (panelHeight <= height - margin * 2 && area <= maxArea && (area <= targetArea * 1.12 || fontSize <= preferredMinFont)) {
      return { x: margin, y: height - margin - panelHeight, width: panelWidth, height: panelHeight, areaRatio: area / (width * height), fontSize, padding, gap, lineHeight, logo, logoBoxWidth, brandFontSize, brandLineHeight, brandLines, brandHeight, headerFontSize, headerLineHeight, headerLines, headerHeight, bodyLines, bodyHeight, footerLines, footerHeight }
    }
    if (fontSize <= 10) throw new WatermarkError('水印内容过多，请缩短施工内容或施工单位名称', 'TEXT_TOO_LONG')
    fontSize -= 1
  }
}
export function watermarkOrientationTransform(orientation: number, width: number, height: number): number[] {
  return ({ 2: [-1, 0, 0, 1, width, 0], 3: [-1, 0, 0, -1, width, height], 4: [1, 0, 0, -1, 0, height], 5: [0, 1, 1, 0, 0, 0], 6: [0, 1, -1, 0, height, 0], 7: [0, -1, -1, 0, height, width], 8: [0, -1, 1, 0, 0, width] } as Record<number, number[]>)[orientation] || [1, 0, 0, 1, 0, 0]
}

export async function generatePhotoWatermark(sourcePath: string, fields: PhotoWatermarkFields, options: PhotoWatermarkOptions = {}): Promise<WatermarkedPhoto> {
  if ((!sourcePath && !options.overlaySize) || /^https?:\/\//i.test(sourcePath)) throw new WatermarkError('请先选择本机照片', 'INVALID_PATH')
  const api = wechat()
  if (!api.createOffscreenCanvas || !api.canvasToTempFilePath || !api.getImageInfo) throw new WatermarkError('当前微信版本不支持生成水印照片，请升级微信', 'UNSUPPORTED')
  const info = options.overlaySize ? { ...options.overlaySize, orientation: 'up', path: '' } : await callback<any>((success, fail) => api.getImageInfo({ src: sourcePath, success, fail }))
  let sourceWidth = Number(info.width)
  let sourceHeight = Number(info.height)
  if (!(sourceWidth > 0 && sourceHeight > 0)) throw new WatermarkError('照片尺寸读取失败', 'INVALID_IMAGE')
  let orientation = ORIENTATIONS[String(info.orientation || 'up')] || 1
  const canvas = api.createOffscreenCanvas({ type: '2d', width: 1, height: 1 })
  try {
    const image = canvas.createImage()
    if (!options.overlaySize) await callback<void>((success, fail) => { image.onload = () => success(); image.onerror = fail; image.src = info.path || sourcePath })
    if (orientation >= 5 && sourceWidth !== sourceHeight && Number(image.width) === sourceHeight && Number(image.height) === sourceWidth) { sourceWidth = Number(image.width); sourceHeight = Number(image.height); orientation = 1 }
    const maxEdge = options.maxEdge === 4096 ? 4096 : 2048
    const ratio = Math.min(1, maxEdge / Math.max(sourceWidth, sourceHeight))
    const drawWidth = Math.max(1, Math.round(sourceWidth * ratio))
    const drawHeight = Math.max(1, Math.round(sourceHeight * ratio))
    const width = orientation >= 5 ? drawHeight : drawWidth
    const height = orientation >= 5 ? drawWidth : drawHeight
    let logo: any = null
    let logoCrop: { x: number; y: number; width: number; height: number } | undefined
    let logoSize: { width: number; height: number } | undefined
    if (options.logoPath) {
      if (/^https?:\/\//i.test(options.logoPath)) throw new WatermarkError('请使用已提供的企业标志', 'INVALID_LOGO')
      logo = canvas.createImage()
      await callback<void>((success, fail) => { logo.onload = () => success(); logo.onerror = fail; logo.src = options.logoPath })
      if (!(Number(logo.width) > 0 && Number(logo.height) > 0)) throw new WatermarkError('企业标志读取失败', 'INVALID_LOGO')
      logoCrop = options.logoCrop || { x: 0, y: 0, width: Number(logo.width), height: Number(logo.height) }
      if (![logoCrop.x, logoCrop.y, logoCrop.width, logoCrop.height].every(Number.isFinite) || logoCrop.x < 0 || logoCrop.y < 0 || logoCrop.width <= 0 || logoCrop.height <= 0 || logoCrop.x + logoCrop.width > Number(logo.width) || logoCrop.y + logoCrop.height > Number(logo.height)) throw new WatermarkError('企业图标区域无效', 'INVALID_LOGO')
      logoSize = { width: logoCrop.width, height: logoCrop.height }
    }
    canvas.width = width; canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!options.overlaySize) {
      ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, width, height)
      ctx.save(); ctx.transform(...watermarkOrientationTransform(orientation, drawWidth, drawHeight)); ctx.drawImage(image, 0, 0, drawWidth, drawHeight); ctx.restore()
    }
    const layout = layoutFixedWatermark(width, height, fields, (text, size) => { ctx.font = `${size}px sans-serif`; return ctx.measureText(text).width }, logoSize)
    const bodyY = layout.y + layout.headerHeight + layout.gap
    const footerY = bodyY + layout.bodyHeight + layout.gap
    ctx.fillStyle = 'rgba(5, 24, 28, 0.62)'
    ctx.fillRect(layout.x, layout.y, layout.width, layout.height)
    ctx.strokeStyle = 'rgba(255,255,255,.32)'; ctx.lineWidth = Math.max(1, layout.fontSize * .035)
    ctx.strokeRect?.(layout.x, layout.y, layout.width, layout.height)
    ctx.beginPath?.(); ctx.moveTo?.(layout.x, bodyY - layout.gap / 2); ctx.lineTo?.(layout.x + layout.width, bodyY - layout.gap / 2); ctx.stroke?.()
    ctx.beginPath?.(); ctx.moveTo?.(layout.x, footerY - layout.gap / 2); ctx.lineTo?.(layout.x + layout.width, footerY - layout.gap / 2); ctx.stroke?.()
    if (layout.logoBoxWidth) {
      ctx.fillStyle = 'rgba(255,255,255,.94)'; ctx.fillRect(layout.x, layout.y, layout.logoBoxWidth, layout.headerHeight)
    }
    if (logo && layout.logo) {
      ctx.drawImage(logo, logoCrop!.x, logoCrop!.y, logoCrop!.width, logoCrop!.height,
        layout.x + (layout.logoBoxWidth - layout.logo.width) / 2,
        layout.y + Math.max(layout.padding, (layout.headerHeight - layout.brandHeight - layout.logo.height - layout.padding) / 2), layout.logo.width, layout.logo.height)
    }
    ctx.fillStyle = '#ffffff'; ctx.strokeStyle = 'rgba(0, 0, 0, 0.9)'; ctx.lineWidth = Math.max(2, layout.fontSize * .07)
    ctx.font = `${layout.fontSize}px sans-serif`; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round'
    const drawLines = (lines: string[], x: number, y: number, lineHeight = layout.lineHeight) => lines.forEach((line, index) => {
      const centerY = y + lineHeight * (index + .5); ctx.strokeText?.(line, x, centerY); ctx.fillText(line, x, centerY)
    })
    ctx.font = `${layout.brandFontSize}px sans-serif`
    ctx.textAlign = 'center'; ctx.fillStyle = '#141414'; ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 1
    drawLines(layout.brandLines, layout.x + layout.logoBoxWidth / 2, layout.y + layout.headerHeight - layout.padding - layout.brandHeight, layout.brandLineHeight)
    ctx.textAlign = 'left'; ctx.fillStyle = '#ffffff'; ctx.strokeStyle = 'rgba(0, 0, 0, 0.9)'; ctx.lineWidth = Math.max(2, layout.fontSize * .07)
    ctx.font = `${layout.headerFontSize}px sans-serif`
    drawLines(layout.headerLines, layout.x + layout.logoBoxWidth + layout.padding, layout.y + (layout.headerHeight - layout.headerLines.length * layout.headerLineHeight) / 2, layout.headerLineHeight)
    ctx.font = `${layout.fontSize}px sans-serif`
    drawLines(layout.bodyLines, layout.x + layout.padding, bodyY + layout.padding)
    drawLines(layout.footerLines, layout.x + layout.padding, footerY + layout.padding)
    const result = await callback<any>((success, fail) => api.canvasToTempFilePath({ canvas, fileType: options.overlaySize ? 'png' : 'jpg', quality: .94, destWidth: width, destHeight: height, success, fail }))
    if (!result?.tempFilePath || result.tempFilePath === sourcePath || result.tempFilePath === info.path) throw new WatermarkError('未能生成独立水印副本，请重试', 'INVALID_OUTPUT')
    return { tempFilePath: String(result.tempFilePath), originalPath: sourcePath, width, height }
  } finally { canvas.width = 1; canvas.height = 1 }
}

/** Native map picker returns a human-readable place; kept for manual-photo compatibility. */
export async function chooseWatermarkLocation(latitude?: number, longitude?: number) {
  return authorizedAction('location', async (api) => {
    if (!api.chooseLocation) throw new WatermarkError('当前微信版本不支持地图选点，请手填地点', 'UNSUPPORTED')
    const center = Number.isFinite(latitude) && Number.isFinite(longitude) ? {latitude,longitude} : {}
    const value = await callback<any>((success,fail) => api.chooseLocation({...center,success,fail}),120000)
    const address = String(value.address || '').trim(), name = String(value.name || '').trim()
    const text = address && name && !address.includes(name) ? `${address} · ${name}` : address || name
    if (!text) throw new WatermarkError('没有取得地名，请选择地图上的地点', 'INVALID_LOCATION')
    return {latitude:Number(value.latitude),longitude:Number(value.longitude),text,label:'拍摄位置' as const}
  })
}