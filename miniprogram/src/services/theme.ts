import { computed, reactive, ref, watch } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { solarDaylight } from './solar-theme'
import { getCurrentWatermarkLocation } from './photo-watermark'
export type ThemeMode = 'auto' | 'light' | 'dark'
const KEY = 'engineering-image:appearance:v1'
const TAB_KEY = 'engineering-image:resolved-theme:v1'
export const themeState = reactive({ mode: 'auto' as ThemeMode, resolved: 'light' as 'light' | 'dark', latitude: null as number | null, longitude: null as number | null, locating: false })
export const THEME_COLORS = {
  dark: { 'segment-bg':'#17282d', 'loading-bg':'rgba(12,24,27,.92)', bg:'#0c181b', surface:'#122024', 'surface-2':'#17282d', top:'#0f444d', 'header-text':'#ffffff', 'header-muted':'#c0d4d7', primary:'#2db9aa', 'primary-strong':'#42d7c2', 'primary-soft':'rgba(45,185,170,.14)', text:'#f5fbfa', muted:'#9eb1b4', line:'#2b4247', warning:'#f1b34b', danger:'#ff6b66', success:'#37c58e', 'on-primary':'#041a1a' },
  light: { 'segment-bg':'#f1f4f5', 'loading-bg':'rgba(255,255,255,.94)', bg:'#ffffff', surface:'#ffffff', 'surface-2':'#f3f5f6', top:'#ffffff', 'header-text':'#183238', 'header-muted':'#4e6970', primary:'#087c70', 'primary-strong':'#087568', 'primary-soft':'rgba(8,117,104,.10)', text:'#183238', muted:'#4e6970', line:'#d5dde0', warning:'#805000', danger:'#b52e28', success:'#087443', 'on-primary':'#ffffff' },
}
export const themeStyle = computed(() => Object.entries(THEME_COLORS[themeState.resolved]).map(([key,value]) => `--${key}:${value}`).join(';') + ';background:var(--bg);color:var(--text)')
export const themeLabel = computed(() => themeState.mode === 'light' ? '浅色' : themeState.mode === 'dark' ? '深色' : '自动 · 跟随系统')
function persist() { uni.setStorageSync(KEY, { mode: themeState.mode, latitude: themeState.latitude, longitude: themeState.longitude }) }
function systemTheme(): 'light' | 'dark' {
  try { return String((uni.getSystemInfoSync() as any).theme || '').toLowerCase() === 'dark' ? 'dark' : 'light' } catch { return 'light' }
}
function syncTabTheme(next: 'light' | 'dark') {
  uni.setStorageSync(TAB_KEY, next)
  try {
    for (const page of getCurrentPages() as any[]) {
      const tabBar = page?.getTabBar?.()
      if (tabBar?.data?.theme !== next) tabBar?.setData?.({ theme: next })
    }
  } catch {}
}
function syncSystemBar(next: 'light' | 'dark') {
  try {
    uni.setNavigationBarColor({
      frontColor: next === 'light' ? '#000000' : '#ffffff',
      backgroundColor: next === 'light' ? '#ffffff' : '#0f444d',
      animation: { duration: 0, timingFunc: 'linear' },
    })
  } catch {}
}
export function refreshTheme(date?: Date) {
  let next: 'light' | 'dark'
  if (themeState.mode !== 'auto') {
    next = themeState.mode
  } else if (date && themeState.latitude !== null && themeState.longitude !== null) {
    const daylight = solarDaylight(date, themeState.latitude, themeState.longitude)
    next = daylight === null ? systemTheme() : daylight ? 'light' : 'dark'
  } else {
    next = systemTheme()
  }
  if (themeState.resolved !== next) themeState.resolved = next
  syncTabTheme(next)
  syncSystemBar(next)
}
export function setThemeLocation(latitude: number, longitude: number) {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return
  themeState.latitude = Math.round(latitude * 10) / 10
  themeState.longitude = Math.round(longitude * 10) / 10
  persist()
}
export function setThemeMode(mode: ThemeMode) { themeState.mode = mode; persist(); refreshTheme() }
export async function locateTheme() {
  if (themeState.locating) return
  themeState.locating = true
  try { const value = await getCurrentWatermarkLocation(); setThemeLocation(value.latitude, value.longitude) }
  finally { themeState.locating = false }
}
export function initializeTheme() {
  const stored = uni.getStorageSync(KEY) || {}
  themeState.mode = ['auto','light','dark'].includes(stored.mode) ? stored.mode : 'auto'
  if (typeof stored.latitude === 'number' && typeof stored.longitude === 'number') {
    themeState.latitude = stored.latitude
    themeState.longitude = stored.longitude
  }
  refreshTheme()
}
export function usePageTheme() {
  const pageStyle = ref(themeStyle.value)
  watch(themeStyle, value => { if (pageStyle.value !== value) pageStyle.value = value })
  onShow(() => {
    initializeTheme()
    const value = themeStyle.value
    if (pageStyle.value !== value) pageStyle.value = value
  })
  return pageStyle
}
export function startTheme() { initializeTheme() }
export function stopTheme() {}
