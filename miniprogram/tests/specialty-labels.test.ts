import { describe, expect, it } from 'vitest'
import { specialtyLabels } from '../src/services/specialty-labels'

describe('specialty navigation terminology', () => {
  it('keeps water-engineering unit labels', () => {
    expect(specialtyLabels('水利工程')).toEqual({ leaf: '单元', path: '选择单位、分部、单元和工序' })
  })
  it('shows highway items without water-engineering units', () => {
    expect(specialtyLabels('公路工程').leaf).toBe('分项')
    expect(specialtyLabels('公路工程').path).not.toContain('单元')
  })
  it('includes municipal inspection batches', () => {
    expect(specialtyLabels('市政工程').leaf).toBe('分项/检验批')
    expect(specialtyLabels('市政工程').path).toContain('检验批')
  })
})
