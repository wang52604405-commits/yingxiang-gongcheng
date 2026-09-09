import { describe, expect, it } from 'vitest'
import { normalizeTreeNode } from '@/api/normalize'
import { mockRequest } from '@/api/mock'
import { flattenDestinations } from '@/services/destination-history'

describe('process names survive both supported tree formats', () => {
  it('merges explicit and child processes without duplicates, blanks or retired child processes', () => {
    const result = normalizeTreeNode({ type: 'unit', code: 'u', name: '单元', processes: [' 钢筋安装 ', '', '模板', null, {}, 7], children: [
      { type: 'process', name: '钢筋安装' }, { type: 'process', name: '混凝土' },
      { type: 'process', name: '停用工序', active: false }, { type: 'other', code: 'x', name: '附属目录' },
    ] })
    expect(result.processes).toEqual(['钢筋安装', '模板', '混凝土'])
    expect(result.children?.map((item) => item.code)).toEqual(['x'])
  })
  it('keeps the normalized mock tree selectable with required process choices', async () => {
    const response = await mockRequest<any>('GET', '/projects/default/tree')
    const nodes = flattenDestinations(response.tree.map(normalizeTreeNode))
    const unit = nodes.find((node) => node.code === 'YNLQ-DY-001')
    expect(unit?.processes).toEqual(['基础清理', '钢筋安装', '模板安装', '混凝土浇筑', '成品外观'])
    expect(unit?.assignment.process_required).toBe(true)
  })
})
