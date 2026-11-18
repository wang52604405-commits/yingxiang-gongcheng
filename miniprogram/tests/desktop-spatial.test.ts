import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
const source = readFileSync(new URL('../../assets/app-A20260910-2.92.js', import.meta.url), 'utf8')
const ctx: any = {}
runInNewContext(source.slice(source.indexOf('    function spatialEditorText('), source.indexOf('    function photoMoveTargetLabel(')), ctx)
describe('spatial editor roundtrip', () => {
  it('retains free text through save, reopen, edit and clear', () => {
    let spatial = ctx.spatialEditorValue({}, '示例段 K0+000—K0+020')
    expect(ctx.spatialEditorText(spatial)).toBe('示例段 K0+000—K0+020')
    spatial = ctx.spatialEditorValue(spatial, 'W01 至 W02')
    expect(ctx.spatialEditorText(spatial)).toBe('W01 至 W02')
    expect(ctx.spatialEditorText(ctx.spatialEditorValue(spatial, ''))).toBe('')
  })
  it('does not erase imported structured values or mix location and spatial fields', () => {
    const original = { stake_start: 'K0+000', stake_end: 'K0+020', well_from: 'W01' }
    expect(ctx.spatialEditorValue(original, ctx.spatialEditorText(original))).toEqual(original)
    const edited = ctx.spatialEditorValue(original, '补充位置')
    expect(edited).toEqual({ ...original, text: '补充位置' })
    expect(original).not.toHaveProperty('text')
    expect(source).not.toContain('archive.location_text ? "" :')
    expect(source).toContain('location_text: $("#photoEditLocationInput")?.value.trim() || ""')
  })
})
