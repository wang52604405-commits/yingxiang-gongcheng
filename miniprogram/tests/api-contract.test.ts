import { describe, expect, it, vi } from 'vitest'
import { batchIdempotencyKey, buildChunkUploadInit, buildPhotoUploadForm, normalizeBatchPayload, photoIdempotencyKey } from '@/api/contracts'
import { normalizeBatch, normalizeCloudPhoto, normalizeMediaUrl, normalizeProject, normalizeTreeNode } from '@/api/normalize'
import { API_BASE_URL } from '@/config/env'
import { apiUploadPhoto } from '@/api/client'
import { normalizeBootstrapResponse } from '@/api/mobile'

describe('移动端 API v1 契约', () => {
  it('批次与照片重复提交保持同一幂等主键', () => {
    const payload = normalizeBatchPayload({
      client_batch_id: '11111111-1111-4111-8111-111111111111',
      project_id: 'YNLQ',
      scope: 'engineering',
      category: 'construction',
      mode: 'direct',
      assignment: { unit_code: 'YNLQ-DY-001', process_name: '钢筋安装' },
    })
    expect(batchIdempotencyKey(payload)).toBe('batch:11111111-1111-4111-8111-111111111111')
    const metadata = {
      photo_uuid: '22222222-2222-4222-8222-222222222222',
      client_captured_at: '2026-08-25T01:02:03Z',
      orientation: 6,
      width: 1_632,
      height: 1_224,
      sha256: 'a'.repeat(64),
      original_size_bytes: 8_321_440,
      original_filename: 'IMG_20260825.png',
      original_mime_type: 'image/png' as const,
      title: '钢筋安装检查',
      photo_date: '2026-08-25',
    }
    expect(photoIdempotencyKey(metadata)).toBe('photo:22222222-2222-4222-8222-222222222222')
    expect(buildPhotoUploadForm(metadata)).toEqual({
      photo_uuid: metadata.photo_uuid,
      client_captured_at: metadata.client_captured_at,
      orientation: '6',
      width: '1632',
      height: '1224',
      sha256: metadata.sha256,
      original_size_bytes: '8321440',
      original_filename: 'IMG_20260825.png',
      original_mime_type: 'image/png',
      title: '钢筋安装检查',
      photo_date: '2026-08-25',
    })
    expect(buildPhotoUploadForm(metadata)).not.toHaveProperty('preview_sha256')
    expect(buildPhotoUploadForm(metadata)).not.toHaveProperty('preview_size')
    expect(buildChunkUploadInit(metadata, 4 * 1024 * 1024)).toEqual({
      photo_uuid: metadata.photo_uuid,
      sha256: metadata.sha256,
      original_size_bytes: metadata.original_size_bytes,
      original_filename: metadata.original_filename,
      chunk_size_bytes: 4 * 1024 * 1024,
      total_chunks: 2,
      client_captured_at: metadata.client_captured_at,
      orientation: 6,
      width: 1_632,
      height: 1_224,
      title: '钢筋安装检查',
      photo_date: '2026-08-25',
    })
    expect(buildChunkUploadInit(metadata, 4 * 1024 * 1024)).not.toHaveProperty('original_mime_type')
  })

  it('按服务器真实的 batch 嵌套结构读取批次与 score/reasons 候选', () => {
    const normalized = normalizeBatch({
      batch_id: 18,
      client_batch_id: 'client-18',
      status: 'needs_review',
      photos: [{
        photo_uuid: 'photo-18',
        status: 'needs_review',
        title: '模板验收',
        photo_date: '2026-08-25',
        match_candidates: [{ unit_code: 'YNLQ-DY-018', name: '闸室段', score: 880, reasons: ['水印单元名称匹配'] }],
      }],
    })
    expect(normalized.batch_id).toBe('18')
    expect(normalized.photos[0].match_candidates[0]).toMatchObject({ unit_code: 'YNLQ-DY-018', unit_name: '闸室段', score: 880, confidence: 0.88 })
    expect(normalized.photos[0].match_candidates[0].reasons).toEqual(['水印单元名称匹配'])
  })

  it('按服务器 project_name/tree/download_url 字段转换为页面模型', () => {
    expect(normalizeProject({ project_id: 'YNLQ', project_code: 'YNLQ', project_name: '邯郸市永年区洺河龙泉缓洪工程', revision: 7 })).toMatchObject({ id: 'YNLQ', code: 'YNLQ', name: '邯郸市永年区洺河龙泉缓洪工程' })
    const node = normalizeTreeNode({ node_code: 'YNLQ-DY-001', node_type: 'unit', name: '进口段', children: [{ node_code: 'p1', node_type: 'process', name: '钢筋安装', children: [] }] })
    expect(node.processes).toEqual(['钢筋安装'])
    expect(node.children).toEqual([])
    expect(normalizeCloudPhoto({ photo_uuid: 'p', title: '现场', photo_date: '2026-08-25', scope: 'engineering', category: 'construction', status: 'desktop_pending', assignment: { unit_code: 'YNLQ-DY-001' }, download_url: 'https://example.test/signed' }).image_url).toBe('https://example.test/signed')
  })

  it('登录响应内嵌 bootstrap 与独立 bootstrap 使用同一转换规则', () => {
    const normalized = normalizeBootstrapResponse({
      account: { id: 32, username: 'tester' },
      current_project: { project_id: 'YNLQ', project_code: 'YNLQ', project_name: '邯郸市永年区洺河龙泉缓洪工程' },
      projects: [{ project_id: 'YNLQ', project_code: 'YNLQ', project_name: '邯郸市永年区洺河龙泉缓洪工程' }],
      queue: { desktop_pending: 2 },
      recent_uploads: [{ photo_uuid: 'p1', scope: 'engineering', category: 'construction', status: 'desktop_pending', download_url: 'https://example.test/p1' }],
    })
    expect(normalized.current_project?.id).toBe('YNLQ')
    expect(normalized.queue.desktop_pending).toBe(2)
    expect(normalized.recent_uploads[0].image_url).toBe('https://example.test/p1')
  })

  it('相对预览地址补 API 域名，OSS 绝对签名地址保持原样', () => {
    expect(normalizeMediaUrl('/api/mobile/v1/files/p1?token=short')).toBe(`${API_BASE_URL}/api/mobile/v1/files/p1?token=short`)
    const signed = 'https://oss.example.test/p1.jpg?Signature=abc'
    expect(normalizeMediaUrl(signed)).toBe(signed)
    const photo = normalizeCloudPhoto({ photo_uuid: 'p1', scope: 'engineering', status: 'desktop_pending', download_url: '/api/mobile/v1/files/p1', thumb_url: signed })
    expect(photo.image_url).toBe(`${API_BASE_URL}/api/mobile/v1/files/p1`)
    expect(photo.thumb_url).toBe(signed)
  })

  it('8MiB 内直传使用微信单请求安全超时，弱网重试仍复用同一 UUID', async () => {
    const uploadFile = vi.fn((options: any) => {
      options.success({ statusCode: 200, data: '{"ok":true}' })
      return { onProgressUpdate: vi.fn() }
    })
    ;(globalThis as any).uni = { getStorageSync: () => 'token', uploadFile }
    await apiUploadPhoto('18', '/user/original.png', {
      photo_uuid: 'photo-timeout',
      client_captured_at: '2026-08-25T01:00:00Z',
      orientation: 1,
      width: 4_000,
      height: 3_000,
      sha256: 'd'.repeat(64),
      original_size_bytes: 7 * 1024 * 1024,
      original_filename: 'original.png',
      original_mime_type: 'image/png',
      title: '',
      photo_date: '2026-08-25',
    })
    expect(uploadFile).toHaveBeenCalledWith(expect.objectContaining({ filePath: '/user/original.png', name: 'file', timeout: 55_000 }))
    expect(uploadFile.mock.calls[0][0].formData.photo_uuid).toBe('photo-timeout')
  })
})
