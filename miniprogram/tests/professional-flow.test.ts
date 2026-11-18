import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { normalizeBatchPayload } from '@/api/contracts'
import { mobileApi } from '@/api/mobile'
import { createPhotoLibrary, destinationPhotoQuery } from '@/services/photo-library'
import type { Assignment, Scope } from '@/types/domain'

const source = (path: string) => readFileSync(resolve(path), 'utf8')

describe('专业采集与全量图库闭环', () => {
  it('专业清单引用随工程批次上传，其它影像不能夹带专业规则', () => {
    const requirement = {
      template_code: 'FJ-JG-001',
      photo_requirement_name: '钢筋安装隐蔽验收',
      required_type: 'required' as const,
    }
    expect(normalizeBatchPayload({
      client_batch_id: '11111111-1111-4111-8111-111111111111',
      project_id: 'default',
      scope: 'engineering',
      category: 'construction',
      mode: 'auto',
      requirement,
    }).requirement).toEqual(requirement)
    expect(normalizeBatchPayload({
      client_batch_id: '22222222-2222-4222-8222-222222222222',
      project_id: 'default',
      scope: 'other',
      mode: 'direct',
      assignment: { other_node_code: 'OTHER-SITE' },
      requirement,
    })).not.toHaveProperty('requirement')
  })

  it('从清单进入采集时保存模板编码，施工监理切换不会被 onShow 旧值覆盖', () => {
    const requirementPage = source('src/pages/requirements/index.vue')
    const uploadPage = source('src/pages/upload/index.vue')
    expect(requirementPage).toContain('template_code: item.template_code')
    expect(uploadPage).toContain('function changeCategory(next: PhotoCategory)')
    expect(uploadPage).toContain('savePreset()')
    expect(uploadPage).toContain('requirement: scope.value ===')
  })

  it('图库使用归档位置筛选并提供持续翻页入口', () => {
    const library = source('src/pages/library/index.vue')
    expect(library).toContain('...destinationPhotoQuery(scope.value, activeDestination.value?.assignment)')
    expect(library).toContain('onReachBottom')
    expect(library).toContain('继续加载更多')
  })

  it.each<[string, Scope, Assignment, string, string]>([
    ['市政分项', 'engineering', { item_code: '分项/001' }, 'item_code', '分项/001'],
    ['水利单元', 'engineering', { unit_code: 'DY-001' }, 'unit_code', 'DY-001'],
    ['其它目录', 'other', { other_node_code: 'QT-001' }, 'other_node_code', 'QT-001'],
  ])('%s筛选传到真实 API，翻页继续携带位置且清除筛选后不残留', async (_, scope, assignment, field, code) => {
    const urls: URL[] = []
    const request = vi.fn((options: any) => {
      const url = new URL(options.url)
      urls.push(url)
      const filtered = url.searchParams.has(field)
      const nextPage = url.searchParams.has('cursor')
      options.success({ statusCode: 200, data: {
        ok: true,
        photos: [{ photo_uuid: filtered ? (nextPage ? 'filtered-2' : 'filtered-1') : 'all-photos' }],
        total: filtered ? 2 : 1,
        next_cursor: filtered && !nextPage ? 'next/2' : '',
      } })
    })
    vi.stubGlobal('uni', { getStorageSync: () => 'token', request })
    try {
      let selected: Assignment | undefined = assignment
      const library = createPhotoLibrary(() => ({
        owner: 'account',
        query: { project_id: '32:工程', scope, ...destinationPhotoQuery(scope, selected) },
      }), mobileApi.photos)
      await library.load()
      await library.load(false)
      expect(library.state.photos.map((photo) => photo.photo_uuid)).toEqual(['filtered-1', 'filtered-2'])
      expect(urls).toHaveLength(2)
      for (const url of urls) {
        expect(url.pathname).toBe('/api/mobile/v1/photos')
        expect(Object.fromEntries(url.searchParams)).toMatchObject({ project_id: '32:工程', scope, [field]: code, limit: '60' })
        for (const otherField of ['item_code', 'unit_code', 'other_node_code'].filter((name) => name !== field)) {
          expect(url.searchParams.has(otherField)).toBe(false)
        }
      }
      expect(urls[0].searchParams.has('cursor')).toBe(false)
      expect(urls[1].searchParams.get('cursor')).toBe('next/2')
      selected = undefined
      await library.load()
      expect(urls).toHaveLength(3)
      expect(urls[2].searchParams.has(field)).toBe(false)
      expect(urls[2].searchParams.has('cursor')).toBe(false)
      expect(library.state.photos.map((photo) => photo.photo_uuid)).toEqual(['all-photos'])
      expect(library.state.error).toBe('')
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
