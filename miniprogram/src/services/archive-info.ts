import type { Assignment, ProjectSummary, UploadDraft } from '@/types/domain'

export interface ArchiveInfoIssue {
  field: 'project' | 'category' | 'unit_project' | 'part' | 'unit' | 'process' | 'other_destination'
  label: string
}

function present(value: unknown): boolean {
  return Boolean(String(value || '').trim())
}

export function resolveDraftProject(projects: ProjectSummary[], projectId: string, accountId: string): ProjectSummary | undefined {
  const wantedProjectId = String(projectId || '').trim()
  if (!wantedProjectId) return undefined
  const exact = projects.find((project) => String(project.id) === wantedProjectId)
  if (exact) return exact
  const wantedOwner = String(accountId || '').trim()
  if (!wantedOwner) return undefined
  return projects.find((project) => (
    String(project.local_project_id || '') === wantedProjectId
    && String(project.owner_account_id || '') === wantedOwner
    && project.can_capture !== false
  ))
}

export function archiveInfoIssues(draft: UploadDraft): ArchiveInfoIssue[] {
  const issues: ArchiveInfoIssue[] = []
  if (!present(draft.project_id) || !present(draft.project_name)) issues.push({ field: 'project', label: '工程' })
  if (draft.scope === 'other') {
    if (!present(draft.assignment?.other_node_code) || !present(draft.assignment?.other_node_name)) {
      issues.push({ field: 'other_destination', label: '其它影像目录' })
    }
    return issues
  }
  if (!draft.category) issues.push({ field: 'category', label: '照片类别' })
  const assignment = draft.assignment
  if (!present(assignment?.unit_project_code) || !present(assignment?.unit_project_name)) {
    issues.push({ field: 'unit_project', label: '单位工程' })
  }
  if (!present(assignment?.part_code) || !present(assignment?.part_name)) {
    issues.push({ field: 'part', label: '分部工程' })
  }
  if (!present(assignment?.unit_code) || !present(assignment?.unit_name)) {
    issues.push({ field: 'unit', label: '单元工程' })
  }
  if (assignment?.process_required && !present(assignment.process_name)) {
    issues.push({ field: 'process', label: '工序' })
  }
  return issues
}

export function isArchiveInfoComplete(draft: UploadDraft): boolean {
  return archiveInfoIssues(draft).length === 0
}

export function archiveInfoMessage(draft: UploadDraft): string {
  const labels = archiveInfoIssues(draft).map((issue) => issue.label)
  return labels.length ? `请完善：${labels.join('、')}` : ''
}

export function hasCompleteEngineeringHierarchy(assignment: Assignment | undefined): boolean {
  if (!assignment) return false
  return present(assignment.unit_project_code)
    && present(assignment.unit_project_name)
    && present(assignment.part_code)
    && present(assignment.part_name)
    && present(assignment.unit_code)
    && present(assignment.unit_name)
    && (!assignment.process_required || present(assignment.process_name))
}
