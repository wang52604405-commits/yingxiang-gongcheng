import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { normalizeBatchPayload } from '@/api/contracts'

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

  it('图库携带其它目录筛选并消费 next_cursor，不再只显示首 60 张', () => {
    const library = source('src/pages/library/index.vue')
    expect(library).toContain('other_node_code:')
    expect(library).toContain('cursor: reset ? undefined : nextCursor.value')
    expect(library).toContain('onReachBottom')
    expect(library).toContain('继续加载更多')
  })
})
