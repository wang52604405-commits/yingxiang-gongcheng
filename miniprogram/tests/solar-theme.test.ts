import { describe, expect, it, beforeEach } from 'vitest'
import { solarDaylight } from '@/services/solar-theme'
import { THEME_COLORS, themeState, refreshTheme, setThemeMode, setThemeLocation, themeStyle } from '@/services/theme'
function luminance(hex: string) { const c = hex.slice(1).match(/../g)!.map(x=>parseInt(x,16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4); return .2126*c[0]+.7152*c[1]+.0722*c[2] }
function contrast(a:string,b:string) { const x=luminance(a),y=luminance(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05) }
beforeEach(() => { (globalThis as any).uni = { setStorageSync() {}, getSystemInfoSync: () => ({theme:'light'}) }; themeState.mode='auto'; themeState.latitude=null; themeState.longitude=null })
describe('按当地日出日落切换', () => {
  it('邯郸春分日前后依据太阳位置切换，不写死六点', () => {
    expect(solarDaylight(new Date('2026-03-20T05:30:00+08:00'),36.6,114.5)).toBe(false)
    expect(solarDaylight(new Date('2026-03-20T07:00:00+08:00'),36.6,114.5)).toBe(true)
    expect(solarDaylight(new Date('2026-03-20T19:00:00+08:00'),36.6,114.5)).toBe(false)
    expect(solarDaylight(new Date('2026-06-21T19:00:00+08:00'),36.6,114.5)).toBe(true)
  })
  it('同一时刻不同经度、跨年及极昼极夜都能判断', () => {
    expect(solarDaylight(new Date('2026-03-20T12:00:00Z'),0,0)).toBe(true)
    expect(solarDaylight(new Date('2026-03-20T12:00:00Z'),0,180)).toBe(false)
    expect(solarDaylight(new Date('2026-06-21T00:00:00Z'),80,0)).toBe(true)
    expect(solarDaylight(new Date('2026-12-21T12:00:00Z'),80,0)).toBe(false)
    expect(solarDaylight(new Date('2028-01-01T12:00:00Z'),0,0)).toBe(true)
    expect(solarDaylight(new Date(),NaN,180)).toBeNull()
  })
  it('无定位跟随系统，手动皮肤优先且自动模式按太阳切换', () => {
    refreshTheme(); expect(themeState.resolved).toBe('light')
    setThemeLocation(36.612345,114.512345)
    expect(themeState.latitude).toBe(36.6)
    refreshTheme(new Date('2026-03-20T19:00:00+08:00')); expect(themeState.resolved).toBe('dark')
    setThemeMode('light'); refreshTheme(new Date('2026-03-20T19:00:00+08:00')); expect(themeState.resolved).toBe('light')
    expect(themeStyle.value).toContain('--surface:#ffffff')
  })
  it('两种皮肤的主文字、次文字、操作文字与卡片均达到可读对比度', () => {
    for (const c of Object.values(THEME_COLORS)) {
      for (const fg of [c.text,c.muted,c['primary-strong'],c.danger]) for (const bg of [c.bg,c.surface,c['surface-2']]) expect(contrast(fg,bg)).toBeGreaterThanOrEqual(4.5)
      expect(contrast(c['on-primary'],c['primary-strong'])).toBeGreaterThanOrEqual(4.5)
    }
  })
})
