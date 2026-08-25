const TAB_PATHS = [
  '/pages/home/index',
  '/pages/library/index',
  '/pages/upload/index',
  '/pages/queue/index',
  '/pages/profile/index',
]

export function switchTab(index: number): void {
  uni.switchTab({ url: TAB_PATHS[index] })
}

export function syncTabBar(index: number): void {
  const page = getCurrentPages().at(-1) as any
  page?.getTabBar?.()?.setData?.({ selected: index })
}
