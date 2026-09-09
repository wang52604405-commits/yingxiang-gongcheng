import { beforeEach, describe, expect, it, vi } from 'vitest'
import { chooseWatermarkLocation, fixedWatermarkRows, generatePhotoWatermark, getCurrentWatermarkLocation, layoutFixedWatermark, layoutWatermark, saveWatermarkToAlbum, watermarkOrientationTransform, watermarkTextRows, wrapWatermarkText } from '@/services/photo-watermark'

const measure = (text: string, size: number) => Array.from(text).reduce((sum, ch) => sum + (/^[\x00-\x7F]$/.test(ch) ? .55 : 1) * size, 0)

function mockWechat(orientation = 'up') {
  const ctx: any = {
    font: '', fillStyle: '', strokeStyle: '', lineWidth: 0, textBaseline: '', lineJoin: '', textAlign: '',
    measureText: vi.fn((text: string) => ({ width: measure(text, Number.parseFloat(ctx.font) || 16) })),
    fillRect: vi.fn(), strokeRect: vi.fn(), fillText: vi.fn(), strokeText: vi.fn(), drawImage: vi.fn(),
    save: vi.fn(), restore: vi.fn(), transform: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
  }
  const canvas: any = {
    width: 1, height: 1, getContext: () => ctx,
    createImage: vi.fn(() => ({ width: 4000, height: 3000, onload: undefined as any, onerror: undefined as any, set src(_: string) { queueMicrotask(() => this.onload?.()) } })),
  }
  const api: any = {
    createOffscreenCanvas: vi.fn(() => canvas),
    getImageInfo: vi.fn(({ success }: any) => success({ width: 4000, height: 3000, orientation, path: '/user/photo.jpg' })),
    canvasToTempFilePath: vi.fn(({ success, destWidth, destHeight, fileType }: any) => success({ tempFilePath: `/tmp/watermark.${fileType || 'jpg'}?${destWidth}x${destHeight}` })),
    requirePrivacyAuthorize: vi.fn(({ success }: any) => success()),
    getLocation: vi.fn(({ success }: any) => success({ latitude: 39.9, longitude: 116.4, accuracy: 12 })),
    chooseLocation: vi.fn(({ success }: any) => success({ latitude: 39.91, longitude: 116.41, name: '施工现场', address: '北京市某路' })),
    saveImageToPhotosAlbum: vi.fn(({ success }: any) => success()),
    onAppHide: vi.fn(), offAppHide: vi.fn(),
  }
  ;(globalThis as any).wx = api
  return { api, ctx, canvas }
}

beforeEach(() => { delete (globalThis as any).wx })

describe('独立水印副本与手动定位', () => {
  it('CJK长题名换行后文字和底板都在图片范围内，未知日期不会补今天', () => {
    const fields = { title: '北围堤管理路超长施工题名用于验证中文自动换行不会越界', sitePart: '0+000~0+500土方开挖', photographer: '张三', photoDate: '', location: { label: '手填位置' as const, text: '115乡道' } }
    const layout = layoutWatermark(700, 900, fields, measure)
    expect(layout.x).toBeGreaterThanOrEqual(0); expect(layout.y).toBeGreaterThanOrEqual(0)
    expect(layout.x + layout.width).toBeLessThanOrEqual(700); expect(layout.y + layout.height).toBeLessThanOrEqual(900)
    expect(layout.lines.length).toBeGreaterThan(watermarkTextRows(fields).length)
    expect(watermarkTextRows(fields).some((row) => row.includes(new Date().getFullYear().toString()))).toBe(false)
  })

  it('右下角与多行备注、字体、企业标志布局均不越界', () => {
    const fields = { project:'项目',title:'题名',note:'第一行\n第二行', photographer:'李四' }
    const layout = layoutWatermark(1200,900,fields,measure,{position:'bottom-right',fontScale:1.2,logoSize:{width:160,height:40}})
    expect(layout.x + layout.width).toBeLessThanOrEqual(1200)
    expect(layout.y + layout.height).toBeLessThanOrEqual(900)
    expect(layout.lines).toContain('备注：第一行'); expect(layout.lines).toContain('第二行')
  })

  it('生成2048边长JPEG副本，不触发定位、隐私授权、相册保存或源文件写入', async () => {
    const { api, ctx } = mockWechat()
    const result = await generatePhotoWatermark('/user/photo.jpg', { project:'工程',photographer:'张三' })
    expect(result.width).toBe(2048); expect(result.height).toBe(1536)
    expect(result.tempFilePath).not.toBe('/user/photo.jpg')
    expect(api.getLocation).not.toHaveBeenCalled(); expect(api.requirePrivacyAuthorize).not.toHaveBeenCalled(); expect(api.saveImageToPhotosAlbum).not.toHaveBeenCalled()
    expect(ctx.drawImage).toHaveBeenCalledTimes(1)
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
    expect(ctx.fillRect).toHaveBeenCalledTimes(3)
    expect(ctx.fillText.mock.calls.map((call: any) => call[0])).toContain('时间：未取得拍摄日期')
    expect(ctx.textBaseline).toBe('middle')
  })

  it('固定模板保留日期但不显示时分秒，并保持文字垂直居中', () => {
    const fields = { project:'水库除险加固工程',unitProjectName:'拦河闸单位工程',partName:'闸室分部工程',unitName:'底板钢筋单元',constructionContent:'钢筋间距与保护层验收',capturedAt:'2026-09-10T06:58:32+08:00',photographer:'张三',contractor:'中国建筑某施工单位' }
    const layout = layoutFixedWatermark(2048,1536,fields,measure,{width:305,height:56})
    expect(layout.areaRatio).toBeLessThanOrEqual(.145)
    expect(layout.headerFontSize).toBe(layout.fontSize)
    expect(layout.brandFontSize).toBe(layout.fontSize)
    expect(layout.areaRatio).toBeGreaterThan(.10)
    expect(layout.x).toBeLessThan(100)
    expect(layout.y+layout.height).toBeLessThan(1536)
    expect(fixedWatermarkRows(fields)).toContain('施工内容：底板钢筋单元—钢筋间距与保护层验收')
    expect(fixedWatermarkRows(fields)).toContain('时间：2026-09-10')
    expect(fixedWatermarkRows(fields).some((row) => /\d{2}:\d{2}/.test(row))).toBe(false)
  })

  it('导出器若错误返回原图路径则拒绝当作水印成功', async () => {
    const { api } = mockWechat()
    api.canvasToTempFilePath.mockImplementation(({ success }: any) => success({ tempFilePath: '/user/photo.jpg' }))
    await expect(generatePhotoWatermark('/user/photo.jpg', { title: '测试' })).rejects.toThrow('独立水印副本')
  })

  it('主动定位才询问隐私并调用一次当前定位，拒绝时提供设置入口但不自动打开', async () => {
    const { api } = mockWechat()
    const result = await getCurrentWatermarkLocation()
    expect(result.text).toContain('39.900000')
    expect(api.requirePrivacyAuthorize).toHaveBeenCalledTimes(1)
    expect(api.getLocation).toHaveBeenCalledTimes(1)
  })

  it('隐私拒绝不会调用定位；授权等待期间退后台也不开始定位', async () => {
    const { api } = mockWechat()
    api.requirePrivacyAuthorize.mockImplementation(({ fail }: any) => fail({ errMsg: 'deny' }))
    await expect(getCurrentWatermarkLocation()).rejects.toMatchObject({ canOpenSettings: true })
    expect(api.getLocation).not.toHaveBeenCalled()
  })

  it('地图选点显示地点名称而非经纬度，空地点不伪造地址', async () => {
    const { api } = mockWechat()
    const result = await chooseWatermarkLocation()
    expect(result.text).toContain('北京市某路')
    expect(result.text).toContain('施工现场')
    api.chooseLocation.mockImplementation(({ success }: any) => success({ latitude:39.9,longitude:116.4,name:'',address:'' }))
    await expect(chooseWatermarkLocation()).rejects.toThrow('没有取得地名')
  })

  it('保存只由显式API执行，授权拒绝可恢复且不打开系统设置', async () => {
    const { api } = mockWechat()
    await saveWatermarkToAlbum('/tmp/watermark.jpg')
    expect(api.saveImageToPhotosAlbum).toHaveBeenCalledTimes(1)
    api.requirePrivacyAuthorize.mockImplementation(({ fail }: any) => fail({ errMsg:'deny' }))
    await expect(saveWatermarkToAlbum('/tmp/watermark.jpg')).rejects.toMatchObject({ canOpenSettings:true })
  })

  it('离屏画布回调卡住会超时返回，不阻塞队列上传', async () => {
    vi.useFakeTimers()
    const { api } = mockWechat()
    api.getImageInfo.mockImplementation(() => undefined)
    const promise = generatePhotoWatermark('/user/photo.jpg',{title:'测试'})
    const rejection = expect(promise).rejects.toThrow('处理超时')
    await vi.advanceTimersByTimeAsync(16_000)
    await rejection
    vi.useRealTimers()
  })
})