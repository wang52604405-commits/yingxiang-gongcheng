import type { Assignment } from '@/types/domain'
import type { DestinationSelection } from '@/stores/selection'
import type { SelectableDestination } from './destination-history'

const key = (owner: string, project: string) => `engineering-image:watermark-division:v1:${encodeURIComponent(owner)}:${encodeURIComponent(project)}`

export function matchesDivisionKeywords(node: SelectableDestination, keyword: string): boolean {
  const text = [node.name, node.code, node.pathLabel, node.assignment.unit_project_code, node.assignment.part_code].join(' ').toLowerCase()
  return keyword.toLowerCase().trim().split(/\s+/).filter(Boolean).every(word => text.includes(word))
}

export function resolveWatermarkDivision(value: DestinationSelection, nodes: SelectableDestination[]): DestinationSelection | null {
  if (value.scope !== 'engineering') return null
  const a = value.assignment
  const node = nodes.find(item => item.type === 'unit' && item.code === a.unit_code
    && (!a.part_code || item.assignment.part_code === a.part_code)
    && (!a.unit_project_code || item.assignment.unit_project_code === a.unit_project_code))
  return node ? { scope: 'engineering', assignment: { ...node.assignment, process_name: '' } } : null
}

export function watermarkDivisionFields(assignment: Assignment) {
  return { unitProjectName: assignment.unit_project_name || '', partName: assignment.part_name || '', unitName: assignment.unit_name || '', unitCode: assignment.unit_code || '' }
}

export function beginWatermarkDivision(owner: string, project: string): void {
  uni.removeStorageSync(key(owner, project))
}
export function saveWatermarkDivision(owner: string, project: string, value: DestinationSelection): void {
  if (!owner || !project || value.scope !== 'engineering' || !value.assignment.unit_code) return
  uni.setStorageSync(key(owner, project), { ...value, project_id: project })
}
export function consumeWatermarkDivision(owner: string, project: string): DestinationSelection | null {
  const name = key(owner, project)
  const result = uni.getStorageSync(name) as DestinationSelection | undefined
  uni.removeStorageSync(name)
  return result?.project_id === project && result.scope === 'engineering' && result.assignment?.unit_code ? result : null
}
