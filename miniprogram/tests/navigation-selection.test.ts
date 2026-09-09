import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

function source(path: string): string {
  return readFileSync(resolve(path), 'utf8')
}

describe('工程与单元选择返回页面后的刷新契约', () => {
  it('影像库在 onShow 重新读取单元，再按新单元加载照片', () => {
    const library = source('src/pages/library/index.vue')
    expect(library).toContain('const selectedDestination = ref(selectionStorage.getLibraryFilter())')
    expect(library).not.toContain('const selectedDestination = computed')

    const onShowBlock = library.match(/onShow\(\(\) => \{[\s\S]*?\n\}\)/)?.[0] || ''
    const refreshIndex = onShowBlock.indexOf('selectedDestination.value = selectionStorage.getLibraryFilter()')
    const loadIndex = onShowBlock.indexOf('void loadPhotos()')
    expect(refreshIndex).toBeGreaterThanOrEqual(0)
    expect(loadIndex).toBeGreaterThan(refreshIndex)
  })

  it('图库单元筛选与采集归档位置使用不同存储入口，并可清除查看全部', () => {
    const library = source('src/pages/library/index.vue')
    const destination = source('src/pages/destination/select.vue')
    expect(library).toContain('selectionStorage.clearLibraryFilter()')
    expect(library).toContain('查看全部')
    expect(destination).toContain("if (returnTarget.value === 'library') selectionStorage.setLibraryFilter(value)")
    expect(destination).toContain('else selectionStorage.setDestination(value)')
  })

  it('旧批次确认页绑定批次工程，并通过独立目的地入口加载该工程树', () => {
    const confirm = source('src/pages/upload/confirm.vue')
    const destination = source('src/pages/destination/select.vue')
    expect(confirm).toContain("const batchProjectId = computed(() => String(batch.value?.draft.project_id || ''))")
    expect(confirm).toContain('mobileApi.projects()')
    expect(confirm).toContain('manualSession.consume(batchProjectId.value)')
    expect(confirm).toContain('if (manual.project_name) batchProjectName.value = String(manual.project_name)')
    expect(confirm).toContain('project_id=${encodeURIComponent(currentBatch.draft.project_id)}')
    expect(confirm).not.toContain('activeProject')
    expect(destination).toContain("targetProjectId.value = returnTarget.value === 'confirm' ? String(query?.project_id || '') : ''")
    expect(destination).toContain('selectionStorage.setConfirmDestination({')
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
