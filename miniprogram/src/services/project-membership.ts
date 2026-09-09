import type { ProjectAccessRole, ProjectSummary } from '@/types/domain'

export const PROJECT_ROLE_LABELS: Record<ProjectAccessRole, string> = {
  owner: '负责人',
  admin: '管理员',
  capturer: '采集员',
  viewer: '只读',
}

export function normalizeProjectRole(value: unknown): ProjectAccessRole | undefined {
  const role = String(value || '').toLowerCase()
  return ['owner', 'admin', 'capturer', 'viewer'].includes(role) ? role as ProjectAccessRole : undefined
}

export function projectRoleLabel(projectOrRole: ProjectSummary | ProjectAccessRole | undefined): string {
  const role = typeof projectOrRole === 'string' ? normalizeProjectRole(projectOrRole) : normalizeProjectRole(projectOrRole?.access_role)
  return role ? PROJECT_ROLE_LABELS[role] : '负责人'
}

/**
 * 权限字段由服务器裁决。没有权限字段的缓存只可能来自多人功能上线前，
 * 当时账号下的工程均为本人工程，因此保留离线采集兼容；服务器仍会逐次校验。
 */
export function canCaptureProject(project: ProjectSummary | null | undefined): boolean {
  if (!project?.id || project.upload_allowed === false) return false
  if (typeof project.can_capture === 'boolean') return project.can_capture
  const role = normalizeProjectRole(project.access_role)
  return role ? role !== 'viewer' : true
}

export function canManageProjectMembers(project: ProjectSummary | null | undefined): boolean {
  if (!project?.id || project.upload_allowed === false) return false
  if (typeof project.can_manage_members === 'boolean') return project.can_manage_members
  const role = normalizeProjectRole(project.access_role)
  return role ? ['owner', 'admin'].includes(role) : true
}

export function projectMemberSummary(project: ProjectSummary | null | undefined): string {
  if (!project?.id) return ''
  const count = Math.max(1, Number(project.member_count || 1))
  return `${count}人 · ${projectRoleLabel(project)}`
}

export function capturePermissionMessage(project: ProjectSummary | null | undefined): { title: string; content: string } | null {
  if (!project?.id) return { title: '还没有工程', content: '请先选择或加入工程。' }
  if (project.upload_allowed === false) return { title: '仅可查看和本地水印', content: '本项目主账号需开通会员，才可上传或修改项目照片。' }
  if (!canCaptureProject(project)) return { title: '当前为只读成员', content: '该角色不能采集影像。' }
  return null
}
