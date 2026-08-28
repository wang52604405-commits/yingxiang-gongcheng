import { describe, expect, it } from 'vitest'
import { archiveInfoIssues, isArchiveInfoComplete, resolveDraftProject } from '@/services/archive-info'
import type { ProjectSummary, UploadDraft } from '@/types/domain'

function engineeringDraft(): UploadDraft {
  return {
    project_id: '32:YNLQ',
    project_name: '邯郸市永年区洺河龙泉缓洪工程',
    scope: 'engineering',
    category: 'construction',
    mode: 'direct',
    capture_source: 'camera',
    transfer_profile: 'jpeg_1m',
    assignment: {
      unit_project_code: 'DW-001',
      unit_project_name: '拦河闸单位工程',
      part_code: 'FB-001',
      part_name: '进口段分部工程',
      unit_code: 'DY-001',
      unit_name: '进口段单元工程',
      process_name: '钢筋安装',
      process_required: true,
    },
  }
}

describe('上传前完整归档信息', () => {
  it('工程、类别、单位、分部、单元和必需工序齐全才允许提交', () => {
    const draft = engineeringDraft()
    expect(isArchiveInfoComplete(draft)).toBe(true)
    expect(archiveInfoIssues(draft)).toEqual([])
  })

  it('有工序的单元未选工序时明确拦截', () => {
    const draft = engineeringDraft()
    draft.assignment!.process_name = ''
    expect(archiveInfoIssues(draft).map((issue) => issue.field)).toEqual(['process'])
    expect(isArchiveInfoComplete(draft)).toBe(false)
  })

  it('父级编码或名称缺失时不把单元名称当作完整层级', () => {
    const draft = engineeringDraft()
    draft.assignment = { unit_code: 'DY-001', unit_name: '进口段单元工程' }
    expect(archiveInfoIssues(draft).map((issue) => issue.field)).toEqual(['unit_project', 'part'])
  })

  it('其它影像只要求工程和独立目录，不伪造工程照片类别', () => {
    const draft: UploadDraft = {
      project_id: '32:YNLQ',
      project_name: '邯郸市永年区洺河龙泉缓洪工程',
      scope: 'other',
      mode: 'direct',
      assignment: { other_node_code: 'QT-001', other_node_name: '临时道路' },
    }
    expect(isArchiveInfoComplete(draft)).toBe(true)
  })

  it('V1.2 旧队列的裸 project_id 只能迁移到当前账号拥有的同 local_project_id 工程', () => {
    const legacyDraft: UploadDraft = {
      project_id: 'YNLQ',
      scope: 'engineering',
      category: 'construction',
      mode: 'direct',
    }
    const projects: ProjectSummary[] = [
      {
        id: '77:YNLQ',
        code: 'YNLQ',
        name: '别人共享的同编号工程',
        owner_account_id: '77',
        local_project_id: 'YNLQ',
        can_capture: true,
      },
      {
        id: '32:YNLQ',
        code: 'YNLQ',
        name: '邯郸市永年区洺河龙泉缓洪工程',
        owner_account_id: '32',
        local_project_id: 'YNLQ',
        can_capture: true,
      },
    ]

    const resolved = resolveDraftProject(projects, legacyDraft.project_id, '32')
    expect(resolved?.id).toBe('32:YNLQ')
    expect(resolved?.name).toBe('邯郸市永年区洺河龙泉缓洪工程')
    expect(resolveDraftProject(projects.slice(0, 1), legacyDraft.project_id, '32')).toBeUndefined()
    expect(resolveDraftProject(projects, '77:YNLQ', '32')?.id).toBe('77:YNLQ')
  })
})
