import { computed, reactive } from 'vue'
import { solarDaylight } from './solar-theme'
import { getCurrentWatermarkLocation } from './photo-watermark'
export type ThemeMode = 'auto' | 'light' | 'dark'
const KEY = 'engineering-image:appearance:v1'
const TAB_KEY = 'engineering-image:resolved-theme:v1'
export const themeState = reactive({ mode: 'auto' as ThemeMode, resolved: 'dark' as 'light' | 'dark', latitude: null as number | null, longitude: null as number | null, locating: false })
export const THEME_COLORS = {
  dark: { bg:'#0c181b', surface:'#122024', 'surface-2':'#17282d', top:'#0f444d', 'header-text':'#ffffff', 'header-muted':'#c0d4d7', primary:'#2db9aa', 'primary-strong':'#42d7c2', 'primary-soft':'rgba(45,185,170,.14)', text:'#f5fbfa', muted:'#9eb1b4', line:'#2b4247', warning:'#f1b34b', danger:'#ff6b66', success:'#37c58e', 'on-primary':'#041a1a' },
  light: { bg:'#ffffff', surface:'#ffffff', 'surface-2':'#f3f5f6', top:'#ffffff', 'header-text':'#183238', 'header-muted':'#4e6970', primary:'#087c70', 'primary-strong':'#087568', 'primary-soft':'rgba(8,117,104,.10)', text:'#183238', muted:'#4e6970', line:'#d5dde0', warning:'#805000', danger:'#b52e28', success:'#087443', 'on-primary':'#ffffff' },
}
export const themeStyle = computed(() => Object.entries(THEME_COLORS[themeState.resolved]).map(([key,value]) => `--${key}:${value}`).join(';') + ';background:var(--bg);color:var(--text)')
export const themeLabel = computed(() => themeState.mode === 'light' ? '白天' : themeState.mode === 'dark' ? '夜间' : themeState.latitude === null ? '自动 · 待定位' : '自动 · 日出日落')
let timer: ReturnType<typeof setInterval> | undefined
let active = false
let lastLocationAt = 0
function persist() { uni.setStorageSync(KEY, { mode: themeState.mode, latitude: themeState.latitude, longitude: themeState.longitude }) }
export function refreshTheme(date = new Date()) {
  let daylight: boolean | null = null
  if (themeState.latitude !== null && themeState.longitude !== null) daylight = solarDaylight(date, themeState.latitude, themeState.longitude)
  let fallback = 'dark'
  try { fallback = String((uni.getSystemInfoSync() as any).theme || 'dark') } catch {}
  themeState.resolved = themeState.mode === 'auto' ? daylight === null ? fallback === 'light' ? 'light' : 'dark' : daylight ? 'light' : 'dark' : themeState.mode
  uni.setStorageSync(TAB_KEY, themeState.resolved)
  try { const pages = getCurrentPages(); const page = pages[pages.length-1] as any; page?.getTabBar?.()?.setData?.({ theme: themeState.resolved }) } catch {}
}
export function setThemeLocation(latitude: number, longitude: number) {
  if (solarDaylight(new Date(),latitude,longitude) === null) return
  // Coarse coordinates suffice for appearance; do not retain precise photo location here.
  themeState.latitude = Math.round(latitude*10)/10; themeState.longitude = Math.round(longitude*10)/10
  lastLocationAt = Date.now(); persist(); refreshTheme()
}
export function setThemeMode(mode: ThemeMode) { themeState.mode = mode; persist(); refreshTheme() }
export async function locateTheme() {
  if (themeState.locating) return
  themeState.locating = true
  try { const value = await getCurrentWatermarkLocation(); if (active) setThemeLocation(value.latitude,value.longitude) }
  finally { themeState.locating = false }
}
export function startTheme() {
  active = true
  const stored = uni.getStorageSync(KEY) || {}
  themeState.mode = ['auto','light','dark'].includes(stored.mode) ? stored.mode : 'auto'
  if (typeof stored.latitude === 'number' && typeof stored.longitude === 'number' && solarDaylight(new Date(),stored.latitude,stored.longitude) !== null) {
    themeState.latitude = stored.latitude; themeState.longitude = stored.longitude
  }
  refreshTheme(); clearInterval(timer); timer = setInterval(refreshTheme,60000)
  if (themeState.mode === 'auto' && Date.now()-lastLocationAt > 30*60000) {
    const wxApi = (globalThis as any).wx
    wxApi?.getSetting?.({ success: (settings: any) => {
      if (!active || !settings.authSetting?.['scope.userLocation']) return
      wxApi.getLocation({ type:'gcj02', isHighAccuracy:false, success:(value:any) => { if(active) setThemeLocation(value.latitude,value.longitude) }, fail() {} })
    } })
  }
}
export function stopTheme() { active = false; clearInterval(timer) }
