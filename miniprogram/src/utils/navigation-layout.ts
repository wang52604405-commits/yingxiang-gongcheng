export interface WindowLayoutInput {
  windowWidth?: number
  statusBarHeight?: number
}

export interface MenuButtonLayoutInput {
  top?: number
  left?: number
  width?: number
  height?: number
}

export interface NavigationLayout {
  statusBarHeight: number
  navigationBarHeight: number
  menuRightClearance: number
  appHeaderHeight: number
  pageHeaderHeight: number
}

function finiteNumber(value: unknown, fallback = 0) {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : fallback
}

export function resolveNavigationLayout(
  windowInfo: WindowLayoutInput = {},
  menuButton: MenuButtonLayoutInput = {},
): NavigationLayout {
  const windowWidth = Math.max(320, finiteNumber(windowInfo.windowWidth, 375))
  const statusBarHeight = Math.max(0, finiteNumber(windowInfo.statusBarHeight))
  const menuTop = finiteNumber(menuButton.top, -1)
  const menuLeft = finiteNumber(menuButton.left, -1)
  const menuWidth = finiteNumber(menuButton.width)
  const menuHeight = finiteNumber(menuButton.height)
  const hasMenuButton = menuTop >= statusBarHeight && menuLeft > 0 && menuWidth > 0 && menuHeight > 0

  const menuGap = hasMenuButton ? Math.max(4, menuTop - statusBarHeight) : 0
  const navigationBarHeight = hasMenuButton ? Math.max(40, menuHeight + menuGap * 2) : 44
  const fallbackClearance = Math.round(windowWidth * 20 / 750)
  const menuRightClearance = hasMenuButton
    ? Math.max(fallbackClearance, Math.round(windowWidth - menuLeft + 8))
    : fallbackClearance

  return {
    statusBarHeight,
    navigationBarHeight,
    menuRightClearance,
    appHeaderHeight: Math.round(statusBarHeight + navigationBarHeight),
    pageHeaderHeight: Math.round(statusBarHeight + navigationBarHeight),
  }
}

export function readNavigationLayout() {
  let windowInfo: WindowLayoutInput = {}
  let menuButton: MenuButtonLayoutInput = {}

  try {
    windowInfo = uni.getWindowInfo()
  } catch {
    try {
      const legacyInfo = uni.getSystemInfoSync()
      windowInfo = {
        windowWidth: legacyInfo.windowWidth,
        statusBarHeight: legacyInfo.statusBarHeight,
      }
    } catch {
      windowInfo = {}
    }
  }

  try {
    menuButton = uni.getMenuButtonBoundingClientRect()
  } catch {
    menuButton = {}
  }

  return resolveNavigationLayout(windowInfo, menuButton)
}
