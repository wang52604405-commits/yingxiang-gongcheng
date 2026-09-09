import type { Assignment, ProjectNode, Scope } from '@/types/domain'
import type { DestinationSelection } from '@/stores/selection'

export type SelectableDestination = ProjectNode & { pathLabel: string; assignment: Assignment }
export interface DestinationHistory { recent: DestinationSelection[]; favorites: DestinationSelection[] }

export function flattenDestinations(nodes: ProjectNode[], ancestors: ProjectNode[] = []): SelectableDestination[] {
  return nodes.filter((node) => node.active !== false).flatMap((node) => {
    const unitProject = [...ancestors].reverse().find((item) => item.type === 'unit_project')
    const part = [...ancestors].reverse().find((item) => item.type === 'part')
    const assignment: Assignment = node.type === 'unit' ? {
      unit_project_code: unitProject?.code, unit_project_name: unitProject?.name,
      part_code: part?.code, part_name: part?.name, unit_code: node.code, unit_name: node.name,
      process_required: Boolean(node.processes?.length),
    } : { other_node_code: node.code, other_node_name: node.name }
    return [{ ...node, pathLabel: ancestors.map((item) => item.name).join(' / '), assignment },
      ...flattenDestinations(node.children || [], [...ancestors, node])]
  })
}

export function destinationKey(value: DestinationSelection): string {
  const a = value.assignment
  return JSON.stringify([value.scope, a.unit_project_code || '', a.part_code || '', a.unit_code || a.other_node_code || '', a.process_name || ''])
}

/** Rebuild from the live tree: stale names, removed nodes and retired processes are never reused. */
export function reconcileDestination(value: DestinationSelection, nodes: SelectableDestination[]): DestinationSelection | null {
  const a = value.assignment
  const node = nodes.find((item) => value.scope === 'engineering'
    ? item.type === 'unit' && item.code === a.unit_code && (!a.part_code || item.assignment.part_code === a.part_code) && (!a.unit_project_code || item.assignment.unit_project_code === a.unit_project_code)
    : item.type === 'other' && item.code === a.other_node_code && !item.children?.length)
  if (!node || (a.process_name && !node.processes?.includes(a.process_name))) return null
  if (node.processes?.length && !a.process_name) return null
  return { ...value, assignment: { ...node.assignment, ...(value.scope === 'engineering' ? { process_name: a.process_name || '' } : {}) } }
}

function storageKey(kind: string, owner: string, projectId: string): string {
  return `engineering-image:${kind}:v1:${encodeURIComponent(owner || 'unbound')}:${encodeURIComponent(projectId)}`
}

export function getDestinationHistory(owner: string, projectId: string): DestinationHistory {
  const stored = uni.getStorageSync(storageKey('destination-history', owner, projectId))
  const valid = (items: unknown): DestinationSelection[] => Array.isArray(items)
    ? items.filter((item) => item && ['engineering', 'other'].includes(item.scope) && item.assignment && (!item.project_id || String(item.project_id) === projectId)) : []
  return { recent: valid(stored?.recent), favorites: valid(stored?.favorites) }
}

export function rememberDestination(owner: string, projectId: string, value: DestinationSelection): void {
  const history = getDestinationHistory(owner, projectId)
  history.recent = [{ ...value, project_id: projectId }, ...history.recent.filter((item) => destinationKey(item) !== destinationKey(value))].slice(0, 8)
  uni.setStorageSync(storageKey('destination-history', owner, projectId), history)
}

export function toggleFavoriteDestination(owner: string, projectId: string, value: DestinationSelection): void {
  const history = getDestinationHistory(owner, projectId)
  const key = destinationKey(value)
  history.favorites = history.favorites.some((item) => destinationKey(item) === key)
    ? history.favorites.filter((item) => destinationKey(item) !== key)
    : [{ ...value, project_id: projectId }, ...history.favorites].slice(0, 20)
  uni.setStorageSync(storageKey('destination-history', owner, projectId), history)
}

export function setPhotoEditDestination(owner: string, projectId: string, value: DestinationSelection): void {
  uni.setStorageSync(storageKey('photo-edit-destination', owner, projectId), { ...value, project_id: projectId })
}

export function consumePhotoEditDestination(owner: string, projectId: string): DestinationSelection | null {
  const key = storageKey('photo-edit-destination', owner, projectId)
  const value = uni.getStorageSync(key) as DestinationSelection | undefined
  uni.removeStorageSync(key)
  return value?.project_id === projectId ? value : null
}

export function destinationLabel(value: DestinationSelection): string {
  const a = value.assignment
  return (value.scope === 'engineering' ? [a.unit_project_name, a.part_name, a.unit_name, a.process_name] : [a.other_node_name]).filter(Boolean).join(' / ')
}
