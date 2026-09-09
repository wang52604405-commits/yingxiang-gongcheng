import { apiRequest } from '@/api/client'
import { normalizeCloudPhoto } from '@/api/normalize'
import type { Assignment } from '@/types/domain'
export const photoActions = {
  async edit(id: string, project: string, fields: { title: string; photo_date: string; assignment?: Assignment }) {
    const result = await apiRequest<any>('PATCH', `/photos/${encodeURIComponent(id)}`, { project_id: project, ...fields })
    return normalizeCloudPhoto(result.photo)
  },
  verifyPassword(project: string, password: string) {
    return apiRequest('POST', `/projects/${encodeURIComponent(project)}/verify-delete-password`, { password })
  },
  delete(id: string, project: string, password: string) {
    return apiRequest('POST', `/photos/${encodeURIComponent(id)}/delete`, { project_id: project, password })
  },
}
