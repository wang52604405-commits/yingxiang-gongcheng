import { describe, expect, it } from 'vitest'
import { normalizeTreeNode, normalizeCloudPhoto } from '@/api/normalize'
import { flattenDestinations, reconcileDestination, destinationLabel } from '@/services/destination-history'
import { destinationPhotoQuery } from '@/services/photo-library'
import { watermarkDivisionFields, resolveWatermarkDivision } from '@/services/watermark-division'

const tree = normalizeTreeNode({ code: 'unit/internal', display_code: '01', name: '单位', type: 'unit_project', children: [{ code: 'part/internal', display_code: '02', name: '分部', type: 'part', children: [{ code: 'item/internal', display_code: '03', name: '分项', type: 'item', children: [{ code: 'batch/internal', display_code: '001', batch_code: '001', batch_name: '第一检验批', name: '第一检验批', node_type: 'batch' }] }] }] })
describe('inspection batches preserve transport identity and original display codes', () => {
  it('keeps parent item and child batch selectable without migrating old assignments', () => {
    const nodes = flattenDestinations([tree])
    const item = nodes.find(n => n.type === 'item')!
    const batch = nodes.find(n => n.type === 'batch')!
    expect(batch.display_code).toBe('001')
    expect(batch.assignment.item_code).toBe('batch/internal')
    expect(batch.assignment.parent_item_code).toBe('03')
    expect(batch.assignment.parent_item_id).toBe('item/internal')
    expect(batch.assignment.batch_code).toBe('001')
    expect(reconcileDestination({ scope: 'engineering', assignment: item.assignment }, nodes)?.assignment.item_code).toBe('item/internal')
    expect(reconcileDestination({ scope: 'engineering', assignment: batch.assignment }, nodes)?.assignment.item_code).toBe('batch/internal')
    expect(destinationLabel({ scope: 'engineering', assignment: batch.assignment })).toContain('分项 / 第一检验批')
    expect(destinationPhotoQuery('engineering', batch.assignment)).toEqual({ item_code: 'batch/internal' })
  })
  it('watermark uses original leaf code but resolves internal identity', () => {
    const nodes = flattenDestinations([tree])
    const a = nodes.find(n => n.type === 'batch')!.assignment
    expect(watermarkDivisionFields(a).unitCode).toBe('001')
    expect(resolveWatermarkDivision({ scope: 'engineering', assignment: a }, nodes)?.assignment.item_code).toBe('batch/internal')
  })
  it('preserves server batch metadata in photo normalization', () => {
    const photo = normalizeCloudPhoto({ photo_uuid: 'p', assignment: { item_code: 'batch/internal', item_name: '批次', node_type: 'batch', batch_code: '001', batch_name: '批次', item_display_code: '001' } })
    expect(photo.node_type).toBe('batch')
    expect(photo.batch_code).toBe('001')
    expect(photo.item_code).toBe('batch/internal')
  })
})
