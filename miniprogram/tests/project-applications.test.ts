import { beforeEach, describe, expect, it, vi } from 'vitest'
const request = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', () => ({ apiRequest: request }))
import { pendingReviewApplications, projectApplicationsApi, type ReviewableProjectApplication } from '@/services/project-applications'

const pending: ReviewableProjectApplication = {
  id: 7, status: 'pending', project_id: '32:YNLQ', project_name: '工程',
  display_name: '张三', phone: '13800138000', role: 'capturer', can_review: true, created_at: '2026-09-09T08:00:00',
}

describe('项目加入审核', () => {
  beforeEach(() => request.mockReset())

  it('仅显示服务器允许本账号审核的当前项目待审申请', () => {
    const rows = [pending, { ...pending, id: 8, can_review: false }, { ...pending, id: 9, project_id: 'another' }, { ...pending, id: 10, status: 'approved' as const }]
    expect(pendingReviewApplications(rows, '32:YNLQ')).toEqual([pending])
  })

  it('请求按项目筛选，不将普通成员自己的申请视为可审核', async () => {
    request.mockResolvedValue({ requests: [pending, { ...pending, id: 8, can_review: false }] })
    expect(await projectApplicationsApi.pending('32:YNLQ')).toEqual([pending])
    expect(request).toHaveBeenCalledWith('GET', '/project-join-requests?project_id=32%3AYNLQ')
  })

  it('无授权或已处理的申请不会发送审核请求', async () => {
    await expect(projectApplicationsApi.review({ ...pending, can_review: false }, 'approve')).rejects.toThrow('无审核权限')
    await expect(projectApplicationsApi.review({ ...pending, status: 'revoked' }, 'approve')).rejects.toThrow('已处理')
    expect(request).not.toHaveBeenCalled()
  })

  it('明确同意与拒绝使用独立端点，失败保留申请供重试', async () => {
    request.mockResolvedValueOnce({ ok: true })
    await projectApplicationsApi.review(pending, 'approve')
    expect(request).toHaveBeenLastCalledWith('POST', '/project-join-requests/7/approve', {})
    request.mockRejectedValueOnce(new Error('网络连接失败'))
    await expect(projectApplicationsApi.review(pending, 'reject')).rejects.toThrow('网络连接失败')
    expect(pending.status).toBe('pending')
    expect(request).toHaveBeenLastCalledWith('POST', '/project-join-requests/7/reject', {})
  })
})

describe('体验模式加入申请与审核', () => {
  beforeEach(() => vi.resetModules())

  it('申请人重新读取 bootstrap 仍无项目，且不能读取审批者示例申请', async () => {
    const { mockRequest } = await import('@/api/mock')
    await mockRequest('POST', '/auth/wechat-join', { invite_code: 'TEAM123456', display_name: '李明', phone: '13900000000' })
    const bootstrap = await mockRequest<any>('GET', '/bootstrap')
    expect(bootstrap.account.id).toBe('mock-applicant')
    expect(bootstrap.projects).toEqual([])
    const list = await mockRequest<any>('GET', '/project-join-requests')
    expect(list.requests).toHaveLength(1)
    expect(list.requests[0].can_review).toBe(false)
  })

  it('负责人按项目读取审批、同意后成员增加，移出后人数恢复', async () => {
    const { mockRequest } = await import('@/api/mock')
    const bootstrap = await mockRequest<any>('GET', '/bootstrap')
    const projectId = bootstrap.projects[0].id
    const list = await mockRequest<any>('GET', `/project-join-requests?project_id=${encodeURIComponent(projectId)}`)
    expect(list.requests[0].can_review).toBe(true)
    await mockRequest('POST', `/project-join-requests/${list.requests[0].id}/approve`, {})
    const endpoint = `/projects/${encodeURIComponent(projectId)}/members`
    const members = await mockRequest<any>('GET', endpoint)
    expect(members.members).toHaveLength(3)
    await mockRequest('DELETE', `${endpoint}/mock-review-applicant`)
    const after = await mockRequest<any>('GET', endpoint)
    expect(after.members).toHaveLength(2)
    expect(after.project.member_count).toBe(2)
  })
})
