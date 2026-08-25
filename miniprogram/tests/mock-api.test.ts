import { describe, expect, it } from 'vitest'
import { mockRequest } from '@/api/mock'

describe('体验环境 API', () => {
  it('专业采集清单有可操作数据且支持类型筛选', async () => {
    const all = await mockRequest<any>('GET', '/projects/default/requirements')
    const required = await mockRequest<any>('GET', '/projects/default/requirements?required_type=required')

    expect(all.summary).toEqual({ total: 3, required: 1, conditional: 1, recommended: 1 })
    expect(all.requirements).toHaveLength(3)
    expect(required.requirements).toHaveLength(1)
    expect(required.requirements[0]).toMatchObject({ template_code: 'SL-JZ-001', required_type: 'required' })
  })

  it('影像库返回与列表一致的总数', async () => {
    const response = await mockRequest<any>('GET', '/photos?project_id=default&scope=engineering&category=construction')

    expect(response.total).toBe(response.photos.length)
    expect(response.total).toBe(2)
  })
})
