import { beforeEach, describe, expect, it } from 'vitest'
import { flattenDestinations } from '@/services/destination-history'
import { beginWatermarkDivision, consumeWatermarkDivision, matchesDivisionKeywords, resolveWatermarkDivision, saveWatermarkDivision, watermarkDivisionFields } from '@/services/watermark-division'
import type { ProjectNode } from '@/types/domain'

const tree: ProjectNode[] = [{ code: 'DW1', name: '拦河闸', type: 'unit_project', children: [
  { code: 'FB1', name: '进口段', type: 'part', children: [{ code: 'DY001', name: '底板混凝土', type: 'unit', processes: ['钢筋安装'] }] },
  { code: 'FB2', name: '消力池', type: 'part', children: [{ code: 'DY001', name: '底板混凝土', type: 'unit', processes: ['模板安装'] }] },
] }]

describe('从导入划分选择水印前缀', () => {
  const storage = new Map<string, unknown>()
  beforeEach(() => {
    storage.clear()
    ;(globalThis as any).uni = { getStorageSync: (key: string) => storage.get(key), setStorageSync: (key: string, value: unknown) => storage.set(key, value), removeStorageSync: (key: string) => storage.delete(key) }
  })
  it('名称、祖先层级及编码可组合搜索，同名单元能按施工区域区分', () => {
    const units = flattenDestinations(tree).filter(item => item.type === 'unit')
    const matches = units.filter(item => matchesDivisionKeywords(item, '进口 底板 dy001'))
    expect(matches).toHaveLength(1)
    expect(matches[0].assignment.part_code).toBe('FB1')
    expect(units.filter(item => matchesDivisionKeywords(item, 'FB2 DW1'))).toHaveLength(1)
    expect(units.filter(item => matchesDivisionKeywords(item, '不存在'))).toHaveLength(0)
  })
  it('选择单元自动带出三项前缀，无需额外选择工序，也不混用同编码的另一分部', () => {
    const selection = resolveWatermarkDivision({ scope: 'engineering', assignment: { unit_code: 'DY001', part_code: 'FB2', unit_project_code: 'DW1' } }, flattenDestinations(tree))!
    expect(watermarkDivisionFields(selection.assignment)).toEqual({ unitProjectName: '拦河闸', partName: '消力池', unitName: '底板混凝土', unitCode: 'DY001' })
    expect(selection.assignment.process_name).toBe('')
    expect(tree[0].children![1].children![0].processes).toEqual(['模板安装'])
  })
  it('选择结果按账号和工程隔离，一次读取，取消不复用上次结果', () => {
    const selection = { scope: 'engineering' as const, assignment: { unit_code: 'DY001', unit_name: '底板' } }
    saveWatermarkDivision('A', 'P1', selection)
    expect(consumeWatermarkDivision('B', 'P1')).toBeNull()
    expect(consumeWatermarkDivision('A', 'P2')).toBeNull()
    expect(consumeWatermarkDivision('A', 'P1')?.assignment.unit_name).toBe('底板')
    expect(consumeWatermarkDivision('A', 'P1')).toBeNull()
    saveWatermarkDivision('A', 'P1', selection)
    beginWatermarkDivision('A', 'P1')
    expect(consumeWatermarkDivision('A', 'P1')).toBeNull()
  })
})
