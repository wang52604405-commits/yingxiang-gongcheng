import { STATUS_LABELS } from '@/services/photo-state'
import type { CloudPhoto, LocalPhoto, PhotoCategory, ProjectNode, Scope } from '@/types/domain'

export interface PhotoHierarchy {
  unitProjectName?: string
  partName?: string
  unitName?: string
}

export interface PhotoDetailRow {
  key: 'title' | 'project' | 'category' | 'unit_project' | 'part' | 'unit' | 'process' | 'directory' | 'captured_at' | 'photographer' | 'uploaded_by' | 'status'
  label: string
  value: string
  accent?: boolean
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const text = String(value || '').trim()
    if (text) return text
  }
  return ''
}

export function resolvePhotoHierarchy(nodes: ProjectNode[], unitCode: string): PhotoHierarchy {
  const targetCode = String(unitCode || '').trim()
  if (!targetCode) return {}

  function visit(node: ProjectNode, ancestors: ProjectNode[]): PhotoHierarchy | null {
    const path = [...ancestors, node]
    if (node.type === 'unit' && node.code === targetCode) {
      return {
        unitProjectName: path.find((item) => item.type === 'unit_project')?.name,
        partName: path.find((item) => item.type === 'part')?.name,
        unitName: node.name,
      }
    }
    for (const child of node.children || []) {
      const found = visit(child, path)
      if (found) return found
    }
    return null
  }

  for (const root of nodes) {
    const found = visit(root, [])
    if (found) return found
  }
  return {}
}

export function photoCategoryLabel(scope: Scope | undefined, category: PhotoCategory | undefined): string {
  if (scope === 'other') return '其它'
  if (category === 'supervision') return '监理'
  if (category === 'construction') return '施工'
  return ''
}

export function formatPhotoCapturedAt(value: unknown): string {
  const source = String(value || '').trim()
  if (!source) return ''
  const parsed = new Date(source)
  if (Number.isNaN(parsed.getTime())) return source.replace('T', ' ').replace(/\.\d{1,3}(?:Z|[+-]\d{2}:?\d{2})?$/, '')
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`
}

export function buildPhotoDetailRows(input: {
  local?: LocalPhoto | null
  cloud?: CloudPhoto | null
  projectName?: string
  hierarchy?: PhotoHierarchy
  localActor?: string
}): PhotoDetailRow[] {
  const local = input.local || null
  const cloud = input.cloud || null
  const assignment = local?.draft.assignment
  const scope = local?.draft.scope || cloud?.scope
  const category = local?.draft.category || cloud?.category
  const hierarchy = input.hierarchy || {}
  const status = local?.status || cloud?.status
  const rows: Array<PhotoDetailRow | null> = [
    { key: 'title', label: '照片名称', value: firstText(local?.title, cloud?.title) },
    { key: 'project', label: '工程', value: firstText(input.projectName, local?.draft.project_name, cloud?.project_name) },
    { key: 'category', label: '类别', value: photoCategoryLabel(scope, category) },
    scope === 'engineering' ? { key: 'unit_project', label: '单位工程', value: firstText(assignment?.unit_project_name, cloud?.unit_project_name, hierarchy.unitProjectName) } : null,
    scope === 'engineering' ? { key: 'part', label: '分部工程', value: firstText(assignment?.part_name, cloud?.part_name, hierarchy.partName) } : null,
    scope === 'engineering' ? { key: 'unit', label: '单元工程', value: firstText(assignment?.unit_name, cloud?.unit_name, hierarchy.unitName) } : null,
    scope === 'engineering' ? { key: 'process', label: '工序', value: firstText(assignment?.process_name, cloud?.process_name) } : null,
    scope === 'other' ? { key: 'directory', label: '归档目录', value: firstText(assignment?.other_node_name, cloud?.other_node_name) } : null,
    { key: 'captured_at', label: '拍摄时间', value: formatPhotoCapturedAt(firstText(local?.client_captured_at, cloud?.captured_at, local?.photo_date, cloud?.photo_date)) },
    { key: 'photographer', label: '拍摄者', value: firstText(cloud?.photographer, local?.draft.capture_source === 'camera' ? input.localActor : '') },
    { key: 'uploaded_by', label: '上传者', value: firstText(cloud?.uploaded_by, local ? input.localActor : '') },
    { key: 'status', label: '上传/归档状态', value: status ? STATUS_LABELS[status] : '', accent: true },
  ]
  return rows.filter((row): row is PhotoDetailRow => Boolean(row?.value))
}
