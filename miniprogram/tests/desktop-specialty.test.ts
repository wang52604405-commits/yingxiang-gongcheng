import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const source = readFileSync(new URL('../../assets/app-A20260910-2.92.js', import.meta.url), 'utf8')
const helpers = source.slice(source.indexOf('    function isItemProject('), source.indexOf('    function mountUnifiedSettings('))
function context(industry: string, selectedProject: Record<string, unknown> | null = null) {
  const state = { projectInfo: { industry }, selectedProject, projects: [] as Record<string, unknown>[] }
  const ctx = { state, projectCode: (p: { project_code?: string }) => p.project_code || "" }
  runInNewContext(helpers, ctx)
  return ctx as typeof ctx & { nodePhotoLabel: () => string; photoMoveTargetLabel: (p: Record<string, unknown>) => string; recentLeafLabel: (r: Record<string, unknown>) => string; collectionLeafLabel: () => string; leafUiText: (s: string, p?: Record<string, unknown>) => string; renderLeafTerminology: () => void; batchParentLabel: (p: Record<string, unknown>) => string; projectLeafLabel: (p: Record<string, unknown>) => string; numberTemplateToReadable: (s: string) => string; readableToNumberTemplate: (s: string) => string }
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
  it('uses specialty counts and actual node labels without changing stored tokens', () => {
    const water = context('水利工程'), highway = context('公路工程'), municipal = context('市政工程')
    expect(water.leafUiText('2 个单元')).toBe('2 个单元')
    expect(highway.leafUiText('搜索单元工程')).toBe('搜索分项工程')
    expect(municipal.leafUiText('全部单元')).toBe('全部工程节点')
    expect(municipal.leafUiText('删除单元', { division_type: 'unit' })).toBe('删除单元')
    expect(municipal.leafUiText('删除单元', { division_type: 'batch' })).toBe('删除检验批')
    municipal.state.projectInfo.industry = '公路工程'
    expect(municipal.collectionLeafLabel()).toBe('分项')
    const html = readFileSync(new URL('../../templates/index.html', import.meta.url), 'utf8')
    expect(html).toContain('data-leaf-label="全部单元"')
    expect(html).toContain('data-leaf-placeholder="搜索单元编号或名称"')
    expect(source).toContain('metricBadge(projectCount(contract), collectionLeafLabel())')
    expect(source).toContain('"{unit_code}"')
    expect(source).toContain('fields["单元工程编码"]')
  })
  it('refreshes only marked labels and never overwrites real project names', () => {
    const label = { dataset: { leafLabel: '全部单元' }, textContent: '', closest: () => null, getAttribute: () => null, setAttribute: () => {} }
    const deleteLabel = { ...label, dataset: { leafLabel: '删除单元' }, closest: () => ({}) }
    const ctx = context('市政工程', { division_type: 'batch' })
    Object.assign(ctx, { document: { querySelectorAll: () => [label, deleteLabel] } })
    ctx.renderLeafTerminology()
    expect(label.textContent).toBe('全部工程节点')
    expect(deleteLabel.textContent).toBe('删除检验批')
    ctx.state.projectInfo.industry = '水利工程'
    ctx.state.selectedProject = { division_type: 'unit' }
    ctx.renderLeafTerminology()
    expect(label.textContent).toBe('全部单元')
    expect(deleteLabel.textContent).toBe('删除单元')
    const html = readFileSync(new URL('../../templates/index.html', import.meta.url), 'utf8')
    for (const id of ['unitTitle', 'unitSub', 'partSub', 'projectPickerSub', 'photoEditSub']) {
      const opening = html.match(new RegExp(`<[^>]*id="${id}"[^>]*>`))?.[0] || ''
      expect(opening).not.toContain('data-leaf-label')
    }
    expect(html).not.toContain('哈希不证明现场事实')
  })
  it('recent uploads use server node kind before the tree has loaded', () => {
    const ctx = context('公路工程')
    expect(ctx.recentLeafLabel({ project_code: 'legacy', node_kind: 'unit', display_code: '01', project_name: '旧水利单元' })).toBe('单元 01 旧水利单元')
    expect(ctx.recentLeafLabel({ project_code: 'batch-key', node_kind: 'batch', display_code: '01', project_name: '第一批' })).toBe('检验批 01 第一批')
  })
  it('disambiguates duplicate original codes and names by complete parent path for moves', () => {
    const ctx = context('市政工程')
    const common = { division_type: 'batch', display_project_code: '001', project_name: '第一批' }
    const a = { ...common, project_code: 'internal-A', source_fields: { 合同或标段名称: '一标', 单位工程名称: '道路', 单位工程编码: 'D1', 子单位工程名称: '东段', 子单位工程编码: 'Z1', 分部工程名称: '路基', 分部工程编码: 'F1', 子分部工程名称: '试验段', 子分部工程编码: 'S1', 分项工程名称: '土方', 分项工程编码: 'A' } }
    const b = { ...common, project_code: 'internal-B', source_fields: { ...a.source_fields, 单位工程编码: 'D2', 分项工程编码: 'B' } }
    const before = JSON.stringify([a, b])
    const labels = [a, b].map(p => ctx.photoMoveTargetLabel(p))
    expect(labels[0]).toBe('一标 / D1 道路 / Z1 东段 / F1 路基 / S1 试验段 / A 土方 / 检验批 · 001 第一批')
    expect(labels[1]).toContain('D2 道路')
    expect(labels[1]).toContain('B 土方')
    expect(labels[0]).not.toBe(labels[1])
    const selectedId = 'internal-B'
    expect([a, b].find(p => p.project_code === selectedId)).toBe(b)
    expect(JSON.stringify([a, b])).toBe(before)
    expect(source).toContain('value="${escapeHtml(projectCode(project))}">${escapeHtml(photoMoveTargetLabel(project))}</option>')
    expect(source).toContain('const targetLabel = photoMoveTargetLabel(targetProject')
    expect(source).not.toContain('或手动补录单元工程')
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
