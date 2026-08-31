import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { canCaptureProject, canManageProjectMembers, capturePermissionMessage, projectMemberSummary, projectRoleLabel } from '@/services/project-membership'
import { applyBootstrap, bootstrapState, clearBootstrapView } from '@/stores/bootstrap'
import { selectionStorage } from '@/stores/selection'
import type { BootstrapResponse, ProjectSummary } from '@/types/domain'

function project(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return { id: '32:YNLQ', code: 'YNLQ', name: '共享工程', ...overrides }
}

describe('共享工程角色与选择状态', () => {
  const storage = new Map<string, any>()

  beforeEach(() => {
    storage.clear()
    ;(globalThis as any).uni = {
      getStorageSync: (key: string) => storage.get(key),
      setStorageSync: (key: string, value: unknown) => storage.set(key, value),
      removeStorageSync: (key: string) => storage.delete(key),
    }
    selectionStorage.clearOwner()
    clearBootstrapView()
  })

  it('按服务端显式权限拦截只读成员，旧版本人工程缓存仍可离线采集', () => {
    expect(canCaptureProject(project({ access_role: 'viewer', can_capture: false }))).toBe(false)
    expect(canCaptureProject(project({ access_role: 'capturer', can_capture: true }))).toBe(true)
    expect(canCaptureProject(project())).toBe(true)
    expect(canManageProjectMembers(project({ access_role: 'admin', can_manage_members: true }))).toBe(true)
    expect(canManageProjectMembers(project({ access_role: 'capturer', can_manage_members: false }))).toBe(false)
    expect(capturePermissionMessage(project({ access_role: 'viewer', can_capture: false }))?.title).toBe('当前为只读成员')
  })

  it('角色显示简洁且成员数有安全默认值', () => {
    expect(projectRoleLabel('owner')).toBe('负责人')
    expect(projectMemberSummary(project({ access_role: 'capturer', member_count: 5 }))).toBe('5人 · 采集员')
    expect(projectMemberSummary(project())).toBe('1人 · 负责人')
  })

  it('加入返回后优先选中新共享工程，不被旧工程选择覆盖', () => {
    selectionStorage.setOwner('A')
    selectionStorage.setProject(project({ id: 'A:old', name: '旧工程' }))
    const joined = project({ id: '32:YNLQ', access_role: 'capturer', member_count: 3, can_capture: true, can_manage_members: false })
    const response: BootstrapResponse = {
      ok: true,
      account: { id: 'A', username: 'member-a' },
      server_time: '2026-08-28T00:00:00Z',
      current_project: project({ id: 'A:old', name: '旧工程' }),
      projects: [project({ id: 'A:old', name: '旧工程' }), joined],
      queue: {},
      recent_uploads: [],
    }
    applyBootstrap('A', response, joined.id)
    expect(bootstrapState.currentProject).toMatchObject({ id: '32:YNLQ', access_role: 'capturer' })
    expect(selectionStorage.getProject()).toMatchObject({ id: '32:YNLQ', can_capture: true })
  })
})

describe('采集权限入口覆盖', () => {
  const source = (path: string) => readFileSync(resolve(path), 'utf8')

  it('Vue、H5、原生 tabBar 与上传页都存在权限闸门', () => {
    expect(source('src/services/capture-entry.ts')).toContain('capturePermissionMessage(project)')
    expect(source('src/components/H5TabBar.vue')).toContain('launchCapture')
    const nativeTab = source('src/custom-tab-bar/index.js')
    expect(nativeTab).toContain('project.can_capture')
    expect(nativeTab).toContain("role!=='viewer'")
    const upload = source('src/pages/upload/index.vue')
    expect(upload).toContain('if (!ensureCapturePermission()) return')
    expect(upload).toContain("query?.autopick === '1' && !sourceInitialized.value && ensureCapturePermission()")
    expect(upload.indexOf('if (!ensureCapturePermission()) return')).toBeLessThan(upload.indexOf('queueRuntime.enqueue'))
  })

  it('产品版本已进入 V1.4 原图分片上传', () => {
    const pkg = JSON.parse(source('package.json'))
    const manifest = JSON.parse(source('src/manifest.json'))
    expect(pkg.version).toBe('1.4.0')
    expect(manifest.versionName).toBe('1.4.0')
    expect(source('src/pages/profile/index.vue')).toContain('工程影像 V1.4.0 · 原图分片上传')
  })
})
