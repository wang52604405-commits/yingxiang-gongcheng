import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { fixedWatermarkRows, generatePhotoWatermark, getCurrentWatermarkLocation, layoutFixedWatermark, layoutWatermark, saveWatermarkToAlbum, watermarkOrientationTransform, watermarkTextRows, wrapWatermarkText } from '@/services/photo-watermark'

const measure = (text: string, size: number) => Array.from(text).length * size
function mockWechat(orientation = 'up') {
  const ctx: any = { fillRect: vi.fn(), save: vi.fn(), restore: vi.fn(), transform: vi.fn(), drawImage: vi.fn(), fillText: vi.fn(), measureText: (text: string) => ({ width: measure(text, Number.parseFloat(ctx.font)) }) }
  const canvas: any = { width: 1, height: 1, getContext: () => ctx, createImage: () => {
    const img: any = { width: 4000, height: 3000 }
    Object.defineProperty(img, 'src', { set: () => { img.onload?.() } })
    return img
  } }
  const api = {
    createOffscreenCanvas: vi.fn(() => canvas),
    getImageInfo: vi.fn(({ src, success }: any) => success({ path: src, width: 4000, height: 3000, orientation })),
    canvasToTempFilePath: vi.fn(({ success }: any) => success({ tempFilePath: '/tmp/watermarked-copy.jpg' })),
    requirePrivacyAuthorize: vi.fn(({ success }: any) => success()),
    getLocation: vi.fn(({ success }: any) => success({ latitude: 30.5, longitude: 120.5, accuracy: 12 })),
    saveImageToPhotosAlbum: vi.fn(({ success }: any) => success()),
    openSetting: vi.fn(), onAppHide: vi.fn(), offAppHide: vi.fn(),
  }
  ;(globalThis as any).wx = api
  return { api, ctx, canvas }
}

describe('独立水印副本与手动定位', () => {
  beforeEach(() => mockWechat())
  afterEach(() => vi.useRealTimers())

  it('CJK长题名换行后文字和底板都在图片范围内，未知日期不会补今天', () => {
    const fields = { project: '工程名称'.repeat(18), title: '混凝土浇筑与钢筋安装验收'.repeat(9), photographer: '张三', location: { label: '当前定位' as const, text: '30.5,120.5' } }
    const layout = layoutWatermark(2048, 1536, fields, measure)
    expect(layout.lines.length).toBeGreaterThan(4)
    expect(layout.x).toBeGreaterThanOrEqual(0)
    expect(layout.y).toBeGreaterThanOrEqual(0)
    expect(layout.x + layout.width).toBeLessThanOrEqual(2048)
    expect(layout.y + layout.height).toBeLessThanOrEqual(1536)
    for (const line of layout.lines) expect(measure(line, layout.fontSize)).toBeLessThanOrEqual(layout.width - 2 * layout.padding)
    expect(watermarkTextRows(fields).some((row) => row.includes('拍摄日期'))).toBe(false)
    expect(watermarkTextRows(fields).some((row) => row.startsWith('当前定位'))).toBe(true)
    expect(wrapWatermarkText('甲乙丙丁', 20, (text) => text.length * 10)).toEqual(['甲乙', '丙丁'])
  })

  it('右下角与多行备注、字体、企业标志布局均不越界', () => {
    const layout = layoutWatermark(800, 600, { title: '基础验收', note: '第一行\n第二行' }, measure, { position: 'bottom-right', fontScale: 1.2, logoSize: { width: 120, height: 50 } })
    expect(layout.x).toBeGreaterThan(400)
    expect(layout.textOffsetY).toBeGreaterThan(50)
    expect(layout.lines).toContain('备注：第一行')
    expect(layout.lines).toContain('第二行')
    expect(layout.x + layout.width).toBeLessThan(800)
    expect(layout.y + layout.height).toBeLessThan(600)
  })

  it('生成2048边长JPEG副本，不触发定位、隐私授权、相册保存或源文件写入', async () => {
    const { api } = mockWechat()
    const result = await generatePhotoWatermark('/user/original.png', { project: '试验工程', title: '施工照片' })
    expect(result).toEqual({ tempFilePath: '/tmp/watermarked-copy.jpg', originalPath: '/user/original.png', width: 2048, height: 1536 })
    expect(api.canvasToTempFilePath.mock.calls[0][0]).toMatchObject({ fileType: 'jpg', quality: .94, destWidth: 2048, destHeight: 1536 })
    expect(api.requirePrivacyAuthorize).not.toHaveBeenCalled()
    expect(api.getLocation).not.toHaveBeenCalled()
    expect(api.saveImageToPhotosAlbum).not.toHaveBeenCalled()
  })

  it('取景水印使用同一绘制器导出透明PNG，不读取或覆盖照片画面', async () => {
    const { api, ctx } = mockWechat()
    const result = await generatePhotoWatermark('camera-pending', { project: '取景工程', photographer: '张三' }, { overlaySize: { width: 900, height: 1200 } })
    expect(api.getImageInfo).not.toHaveBeenCalled()
    expect(ctx.drawImage).not.toHaveBeenCalled()
    expect(ctx.fillRect.mock.calls.some((c: any[]) => c[0] === 0 && c[1] === 0 && c[2] === 900 && c[3] === 1200)).toBe(false)
    expect(api.canvasToTempFilePath.mock.calls[0][0].fileType).toBe('png')
    expect(result).toMatchObject({ width: 900, height: 1200 })
    expect(api.saveImageToPhotosAlbum).not.toHaveBeenCalled()
  })

  it('原图方向right旋转90度且保留画幅，水印在旋转后的图片上绘制', async () => {
    const { ctx } = mockWechat('right')
    const result = await generatePhotoWatermark('/user/photo.jpg', { title: '竖图' })
    expect(result.width).toBe(1536)
    expect(result.height).toBe(2048)
    expect(ctx.transform).toHaveBeenCalledWith(0, 1, -1, 0, 1536, 0)
    expect(ctx.restore.mock.invocationCallOrder[0]).toBeLessThan(ctx.fillText.mock.invocationCallOrder[0])
    expect(watermarkOrientationTransform(2, 100, 80)).toEqual([-1, 0, 0, 1, 100, 0])
  })

  it('只有明确选择的标志才绘入白底区域，4096模式不会放大小图', async () => {
    const { ctx } = mockWechat()
    const result = await generatePhotoWatermark('/user/photo.jpg', { note: '现场检查\n留存副本' }, { maxEdge: 4096, logoPath: '/static/company-logos/crec.png', position: 'bottom-right', fontScale: .85, opacity: .9 })
    expect(result.width).toBe(4000)
    expect(result.height).toBe(3000)
    expect(ctx.drawImage).toHaveBeenCalledTimes(2)
    expect(ctx.fillRect).toHaveBeenCalledTimes(4) // 正文按参考直接叠在照片上，不铺底色
    expect(ctx.fillText.mock.calls.map((call: any) => call[0])).toContain('时间：未取得原始拍摄时间')
  })

  it('固定模板左下角、统一字号且约占八分之一，施工内容为单元加手填文字，未知时间不伪造', () => {
    const fields = { project:'水库除险加固工程',unitProjectName:'拦河闸单位工程',partName:'闸室分部工程',unitName:'底板钢筋单元',constructionContent:'钢筋间距与保护层验收',photographer:'张三',contractor:'中国建筑某施工单位' }
    const layout = layoutFixedWatermark(2048,1536,fields,measure,{width:305,height:56})
    expect(layout.areaRatio).toBeLessThanOrEqual(.145)
    expect(layout.headerFontSize).toBe(layout.fontSize)
    expect(layout.brandFontSize).toBe(layout.fontSize)
    expect(layout.areaRatio).toBeGreaterThan(.10)
    expect(layout.x).toBeLessThan(100)
    expect(layout.y+layout.height).toBeLessThan(1536)
    expect(fixedWatermarkRows(fields)).toContain('施工内容：底板钢筋单元—钢筋间距与保护层验收')
    expect(fixedWatermarkRows(fields)).toContain('时间：未取得原始拍摄时间')
    expect(layout.footerLines.join('')).toContain('施工单位：中国建筑某施工单位')
  })

  it('导出器若错误返回原图路径则拒绝当作水印成功', async () => {
    const { api } = mockWechat()
    api.canvasToTempFilePath.mockImplementation(({ success }: any) => success({ tempFilePath: '/user/original.jpg' }))
    await expect(generatePhotoWatermark('/user/original.jpg', { title: '照片' })).rejects.toMatchObject({ code: 'INVALID_OUTPUT' })
    expect(api.saveImageToPhotosAlbum).not.toHaveBeenCalled()
  })

  it('主动定位才询问隐私并调用一次当前定位，拒绝时提供设置入口但不自动打开', async () => {
    const { api } = mockWechat()
    const location = await getCurrentWatermarkLocation()
    expect(location).toMatchObject({ latitude: 30.5, longitude: 120.5, accuracy: 12, label: '当前定位', coordinateSystem: 'gcj02' })
    expect(api.requirePrivacyAuthorize).toHaveBeenCalledTimes(1)
    expect(api.getLocation).toHaveBeenCalledTimes(1)
    api.getLocation.mockImplementation(({ fail }: any) => fail({ errMsg: 'getLocation:fail auth deny' }))
    await expect(getCurrentWatermarkLocation()).rejects.toMatchObject({ code: 'PERMISSION_DENIED', canOpenSettings: true })
    expect(api.openSetting).not.toHaveBeenCalled()
  })

  it('隐私拒绝不会调用定位；授权等待期间退后台也不开始定位', async () => {
    const { api } = mockWechat()
    api.requirePrivacyAuthorize.mockImplementation(({ fail }: any) => fail({ errMsg: 'privacy deny' }))
    await expect(getCurrentWatermarkLocation()).rejects.toMatchObject({ code: 'PERMISSION_DENIED' })
    expect(api.getLocation).not.toHaveBeenCalled()
    api.requirePrivacyAuthorize.mockImplementation(({ success }: any) => { (api.onAppHide.mock.calls.at(-1) as any)[0](); success() })
    await expect(getCurrentWatermarkLocation()).rejects.toMatchObject({ code: 'BACKGROUND' })
    expect(api.getLocation).not.toHaveBeenCalled()
  })

  it('保存只由显式API执行，授权拒绝可恢复且不打开系统设置', async () => {
    const { api } = mockWechat()
    await saveWatermarkToAlbum('/tmp/copy.jpg')
    expect(api.saveImageToPhotosAlbum).toHaveBeenCalledTimes(1)
    expect(api.saveImageToPhotosAlbum.mock.calls[0][0]).toMatchObject({ filePath: '/tmp/copy.jpg' })
    api.saveImageToPhotosAlbum.mockImplementation(({ fail }: any) => fail({ errMsg: 'saveImageToPhotosAlbum:fail auth denied' }))
    await expect(saveWatermarkToAlbum('/tmp/copy.jpg')).rejects.toMatchObject({ code: 'PERMISSION_DENIED', canOpenSettings: true })
    expect(api.openSetting).not.toHaveBeenCalled()
  })

  it('离屏画布回调卡住会超时返回，不阻塞队列上传', async () => {
    vi.useFakeTimers()
    const { api } = mockWechat()
    api.canvasToTempFilePath.mockImplementation(() => undefined)
    const pending = generatePhotoWatermark('/user/original.jpg', { title: '验收' })
    const check = expect(pending).rejects.toMatchObject({ code: 'TIMEOUT' })
    await vi.advanceTimersByTimeAsync(16_000)
    await check
  })
})
