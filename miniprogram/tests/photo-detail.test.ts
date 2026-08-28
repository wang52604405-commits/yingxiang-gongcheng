import { describe, expect, it } from 'vitest'
import { normalizeCloudPhoto } from '@/api/normalize'
import { buildPhotoDetailRows, photoCategoryLabel, resolvePhotoHierarchy } from '@/services/photo-detail'
import type { LocalPhoto, ProjectNode } from '@/types/domain'

const projectTree: ProjectNode[] = [{
  code: 'HT-001',
  name: '合同工程',
  type: 'contract',
  children: [{
    code: 'DW-001',
    name: '洺河龙泉缓洪工程',
    type: 'unit_project',
    children: [{
      code: 'FB-001',
      name: '拦河闸工程',
      type: 'part',
      children: [{ code: 'DY-001', name: '拦河闸进口段', type: 'unit' }],
    }],
  }],
}]

describe('照片详情字段', () => {
  it('从工程树精确解析单位、分部和单元工程', () => {
    expect(resolvePhotoHierarchy(projectTree, 'DY-001')).toEqual({
      unitProjectName: '洺河龙泉缓洪工程',
      partName: '拦河闸工程',
      unitName: '拦河闸进口段',
    })
    expect(resolvePhotoHierarchy(projectTree, 'missing')).toEqual({})
  })

  it('服务器照片保留工程引用及已有层级字段', () => {
    const photo = normalizeCloudPhoto({
      photo_uuid: 'photo-1',
      project_ref: '32:YNLQ',
      scope: 'engineering',
      category: 'construction',
      status: 'desktop_pending',
      assignment: { unit_code: 'DY-001' },
      match: { candidates: [{ unit_code: 'DY-001', unit_name: '拦河闸进口段', unit_project_name: '洺河龙泉缓洪工程', part_name: '拦河闸工程' }] },
    })
    expect(photo).toMatchObject({
      project_id: '32:YNLQ',
      unit_project_name: '洺河龙泉缓洪工程',
      part_name: '拦河闸工程',
    })
  })

  it('识别候选的单元名称绝不冒充单位工程名称', () => {
    const photo = normalizeCloudPhoto({
      photo_uuid: 'photo-no-parent',
      scope: 'engineering',
      status: 'needs_review',
      match: { candidates: [{ unit_code: 'DY-001', unit_name: '拦河闸进口段' }] },
    })
    expect(photo.unit_project_name).toBe('')
  })

  it('只生成有值的详情行，并分开拍摄者与上传者', () => {
    const cloud = normalizeCloudPhoto({
      photo_uuid: 'photo-2',
      project_ref: '32:YNLQ',
      title: '钢筋安装检查',
      scope: 'engineering',
      category: 'supervision',
      status: 'desktop_imported',
      assignment: { unit_code: 'DY-001', process_name: '钢筋安装' },
      client_captured_at: '2026-08-28T09:08:07',
      photographer: '张三',
      uploaded_by: '李四',
    })
    const rows = buildPhotoDetailRows({ cloud, projectName: '邯郸市永年区洺河龙泉缓洪工程', hierarchy: resolvePhotoHierarchy(projectTree, 'DY-001') })
    expect(Object.fromEntries(rows.map((row) => [row.label, row.value]))).toMatchObject({
      '工程': '邯郸市永年区洺河龙泉缓洪工程',
      '类别': '监理',
      '单位工程': '洺河龙泉缓洪工程',
      '分部工程': '拦河闸工程',
      '单元工程': '拦河闸进口段',
      '工序': '钢筋安装',
      '拍摄时间': '2026-08-28 09:08:07',
      '拍摄者': '张三',
      '上传者': '李四',
      '上传/归档状态': '已归档',
    })
    expect(rows.some((row) => !row.value)).toBe(false)
  })

  it('本地相册照片不猜测拍摄者，其它影像不显示工程层级空行', () => {
    const local = {
      title: '临时道路巡查',
      client_captured_at: '2026-08-28T10:00:00',
      draft: { project_id: '32:YNLQ', scope: 'other', mode: 'direct', capture_source: 'album', assignment: { other_node_name: '临时道路' } },
      status: 'local_ready',
    } as LocalPhoto
    const rows = buildPhotoDetailRows({ local, localActor: '李四' })
    expect(photoCategoryLabel('other', undefined)).toBe('其它')
    expect(Object.fromEntries(rows.map((row) => [row.label, row.value]))).toMatchObject({
      '类别': '其它',
      '归档目录': '临时道路',
      '上传者': '李四',
      '上传/归档状态': '待上传',
    })
    expect(rows.map((row) => row.label)).not.toContain('拍摄者')
    expect(rows.map((row) => row.label)).not.toContain('单位工程')
  })
})
