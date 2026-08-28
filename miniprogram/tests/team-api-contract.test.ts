import { describe, expect, it } from 'vitest'
import { mockRequest } from '@/api/mock'
import { buildChunkUploadInit, buildPhotoUploadForm, normalizeBatchPayload } from '@/api/contracts'
import { normalizeCloudPhoto, normalizeProject } from '@/api/normalize'

describe('项目成员与邀请 API 契约', () => {
  it('canonical 工程引用和权限字段完整转换', () => {
    expect(normalizeProject({
      project_ref: '32:YNLQ', project_id: '32:YNLQ', project_code: 'YNLQ', project_name: '共享工程',
      owner_account_id: 32, local_project_id: 'YNLQ', access_role: 'viewer', member_count: 6,
      can_capture: false, can_manage_members: false,
    })).toMatchObject({
      id: '32:YNLQ', owner_account_id: '32', local_project_id: 'YNLQ', access_role: 'viewer',
      member_count: 6, can_capture: false, can_manage_members: false,
    })
  })

  it('Mock 覆盖成员列表、邀请、预览、加入、改角色和移除', async () => {
    const ref = encodeURIComponent('mock-account:default')
    const members = await mockRequest<any>('GET', `/projects/${ref}/members`)
    expect(members.members).toHaveLength(2)
    const created = await mockRequest<any>('POST', `/projects/${ref}/invites`, { role: 'viewer' })
    expect(created.invite).toMatchObject({ code: 'TEAM123456', role: 'viewer' })
    const preview = await mockRequest<any>('POST', '/project-invites/preview', { code: 'TEAM123456' })
    expect(preview.invite.project.project_id).toBe('mock-account:default')
    const joined = await mockRequest<any>('POST', '/project-invites/join', { code: 'TEAM123456' })
    expect(joined.project.access_role).toBe('capturer')
    const updated = await mockRequest<any>('PATCH', `/projects/${ref}/members/mock-capturer`, { role: 'viewer' })
    expect(updated.member.role).toBe('viewer')
    const removed = await mockRequest<any>('DELETE', `/projects/${ref}/members/mock-capturer`)
    expect(removed.removed).toBe(true)
  })

  it('新采集把来源传给批次、直传和分片，人员身份不由客户端提交', () => {
    const batch = normalizeBatchPayload({ client_batch_id: 'batch', project_id: '32:YNLQ', scope: 'engineering', category: 'construction', mode: 'direct', capture_source: 'camera' })
    expect(batch.capture_source).toBe('camera')
    const metadata = {
      photo_uuid: 'photo', client_captured_at: '2026-08-28T00:00:00Z', orientation: 1, width: 100, height: 100,
      sha256: 'a'.repeat(64), original_size_bytes: 5_000_000, original_filename: 'photo.jpg', original_mime_type: 'image/jpeg' as const,
      title: '现场照片', photo_date: '2026-08-28', capture_source: 'camera' as const,
    }
    expect(buildPhotoUploadForm(metadata)).toMatchObject({ capture_source: 'camera' })
    expect(buildChunkUploadInit(metadata, 4 * 1024 * 1024)).toMatchObject({ capture_source: 'camera' })
    expect(buildPhotoUploadForm(metadata)).not.toHaveProperty('uploaded_by_account_id')
    expect(buildPhotoUploadForm(metadata)).not.toHaveProperty('photographer_account_id')
  })

  it('照片响应分别保留拍摄者、上传者及永久账号标识', () => {
    expect(normalizeCloudPhoto({
      photo_uuid: 'photo', scope: 'engineering', status: 'desktop_pending', capture_source: 'camera',
      photographer: '张三', photographer_account_id: 101, uploaded_by: '李四', uploaded_by_account_id: 102,
    })).toMatchObject({
      capture_source: 'camera', photographer: '张三', photographer_account_id: '101', uploaded_by: '李四', uploaded_by_account_id: '102',
    })
  })
})
