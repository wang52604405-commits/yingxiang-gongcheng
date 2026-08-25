import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

function source(path: string): string {
  return readFileSync(resolve(path), 'utf8')
}

describe('工程与单元选择返回页面后的刷新契约', () => {
  it('影像库在 onShow 重新读取单元，再按新单元加载照片', () => {
    const library = source('src/pages/library/index.vue')
    expect(library).toContain('const selectedDestination = ref(selectionStorage.getDestination())')
    expect(library).not.toContain('const selectedDestination = computed')

    const onShowBlock = library.match(/onShow\(\(\) => \{[\s\S]*?\n\}\)/)?.[0] || ''
    const refreshIndex = onShowBlock.indexOf('selectedDestination.value = selectionStorage.getDestination()')
    const loadIndex = onShowBlock.indexOf('void loadPhotos()')
    expect(refreshIndex).toBeGreaterThanOrEqual(0)
    expect(loadIndex).toBeGreaterThan(refreshIndex)
  })

  it('所有保留实例的主 Tab 在 onShow 读取当前工程', () => {
    const pages = new Map([
      ['src/pages/home/index.vue', 'fallbackProject.value = selectionStorage.getProject()'],
      ['src/pages/library/index.vue', 'project.value = selectionStorage.getProject()'],
      ['src/pages/upload/index.vue', 'project.value = selectionStorage.getProject()'],
      ['src/pages/queue/index.vue', 'project.value = selectionStorage.getProject()'],
      ['src/pages/profile/index.vue', 'project.value = selectionStorage.getProject()'],
    ])
    for (const [path, expectedRefresh] of pages) {
      const onShowBlock = source(path).match(/onShow\(\(\) => \{[\s\S]*?\n\}\)/)?.[0] || ''
      expect(onShowBlock).toContain(expectedRefresh)
    }
  })
})
