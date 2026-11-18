import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const source = readFileSync(new URL('../../assets/app-A20260910-2.92.js', import.meta.url), 'utf8')
const helpers = source.slice(source.indexOf('    function isItemProject('), source.indexOf('    function mountUnifiedSettings('))
function context(industry: string, selectedProject: Record<string, unknown> | null = null) {
  const state = { projectInfo: { industry }, selectedProject }
  const ctx = { state }
  runInNewContext(helpers, ctx)
  return ctx as typeof ctx & { nodePhotoLabel: () => string; batchParentLabel: (p: Record<string, unknown>) => string; projectLeafLabel: (p: Record<string, unknown>) => string; numberTemplateToReadable: (s: string) => string; readableToNumberTemplate: (s: string) => string }
}
describe('desktop specialty labels preserve original node identity', () => {
  it('uses item labels for municipal/highway nodes', () => {
    for (const industry of ['市政工程', '公路工程']) expect(context(industry, { division_type: 'item' }).nodePhotoLabel()).toBe('分项照片')
  })
  it('shows inspection batches separately', () => {
    expect(context('市政工程', { division_type: 'batch' }).nodePhotoLabel()).toBe('检验批照片')
  })
  it('distinguishes equal batch codes under different parent items', () => {
    const ctx = context('市政工程')
    const a = { division_type: 'batch', display_project_code: '001', source_fields: { 分项工程编码: 'A', 分项工程名称: '钢筋' } }
    const b = { division_type: 'batch', display_project_code: '001', source_fields: { 分项工程编码: 'B', 分项工程名称: '模板' } }
    expect(ctx.batchParentLabel(a)).toBe('A 钢筋')
    expect(ctx.batchParentLabel(b)).toBe('B 模板')
    expect(ctx.projectLeafLabel(a)).toBe('检验批')
    expect(ctx.projectLeafLabel({ division_type: 'item' })).toBe('分项')
    expect(ctx.batchParentLabel({ division_type: 'item' })).toBe('')
    expect(source).toContain('所属分项：${escapeHtml(batchParentLabel(project))}')
    expect(source).toContain('batchParentLabel(project) ? `分项 ${batchParentLabel(project)}`')
  })
  it('keeps legacy water units despite a specialty change', () => {
    expect(context('公路工程', { division_type: 'unit' }).nodePhotoLabel()).toBe('单元照片')
    expect(context('市政工程', { source_fields: { 单元工程编码: '001' } }).nodePhotoLabel()).toBe('单元照片')
  })
  it('does not change the persisted numbering token when its label changes', () => {
    const ctx = context('公路工程')
    const readable = ctx.numberTemplateToReadable('{unit_code}-SY{seq}')
    expect(readable).toBe('【节点编号】-SY【流水号】')
    expect(ctx.readableToNumberTemplate(readable)).toBe('{unit_code}-SY{seq}')
    expect(context('水利工程').numberTemplateToReadable('{unit_code}')).toBe('【单元编号】')
  })
})
