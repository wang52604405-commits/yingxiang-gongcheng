import { apiRequest } from '@/api/client'

export interface ReviewableProjectApplication {
  id: string | number
  status: 'pending' | 'approved' | 'rejected' | 'expired' | 'revoked'
  project_id: string
  project_name: string
  display_name: string
  phone: string
  role: string
  can_review: boolean
  created_at: string
}

/** Server grants authority per invitation; a local admin role alone is insufficient. */
export function pendingReviewApplications(rows: ReviewableProjectApplication[], projectId: string): ReviewableProjectApplication[] {
  return rows.filter((row) => row.project_id === projectId && row.can_review === true && row.status === 'pending')
}

export const projectApplicationsApi = {
  async pending(projectId: string): Promise<ReviewableProjectApplication[]> {
    const response = await apiRequest<{ requests: ReviewableProjectApplication[] }>('GET', `/project-join-requests?project_id=${encodeURIComponent(projectId)}`)
    return pendingReviewApplications(response.requests || [], projectId)
  },
  async review(application: ReviewableProjectApplication, decision: 'approve' | 'reject'): Promise<void> {
    if (!application.can_review || application.status !== 'pending') throw new Error('该申请已处理或无审核权限')
    await apiRequest('POST', `/project-join-requests/${encodeURIComponent(String(application.id))}/${decision}`, {})
  },
}
