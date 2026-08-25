import { describe, expect, it } from 'vitest'
import { resolveNavigationLayout } from '@/utils/navigation-layout'

describe('navigation layout', () => {
  it('uses the real iPhone status bar and WeChat capsule geometry', () => {
    const layout = resolveNavigationLayout(
      { windowWidth: 430, statusBarHeight: 47 },
      { top: 53, left: 330, width: 88, height: 32 },
    )

    expect(layout.statusBarHeight).toBe(47)
    expect(layout.navigationBarHeight).toBe(44)
    expect(layout.menuRightClearance).toBe(108)
    expect(layout.pageHeaderHeight).toBe(91)
    expect(layout.appHeaderHeight).toBe(129)
  })

  it('keeps Android navigation compact while clearing the capsule', () => {
    const layout = resolveNavigationLayout(
      { windowWidth: 360, statusBarHeight: 24 },
      { top: 28, left: 266, width: 86, height: 32 },
    )

    expect(layout.navigationBarHeight).toBe(40)
    expect(layout.menuRightClearance).toBe(102)
    expect(layout.appHeaderHeight).toBe(102)
  })

  it('falls back safely when a platform has no WeChat capsule', () => {
    const layout = resolveNavigationLayout({ windowWidth: 375, statusBarHeight: 0 })

    expect(layout.navigationBarHeight).toBe(44)
    expect(layout.menuRightClearance).toBe(10)
    expect(layout.pageHeaderHeight).toBe(44)
    expect(layout.appHeaderHeight).toBe(82)
  })
})
