import { beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { consumePendingInvite, normalizeInviteCode, peekPendingInvite, inviteCodeForJoinPage, isDiscardedInviteEntry, invalidatePendingInvite, isHandledLaunchInvite, rememberLaunchInvite, rememberPendingInvite } from '@/services/pending-invite'

describe('登录前邀请码保留', () => {
  const storage = new Map<string, any>()

  beforeEach(() => {
    storage.clear()
    ;(globalThis as any).uni = {
      getStorageSync: (key: string) => storage.get(key),
      setStorageSync: (key: string, value: unknown) => storage.set(key, value),
      removeStorageSync: (key: string) => storage.delete(key),
    }
  })

  it('统一清理空格和连字符，只接受 10 位邀请码', () => {
    expect(normalizeInviteCode(' team1-23456 ')).toBe('TEAM123456')
    expect(rememberPendingInvite('short', 1_000)).toBe('')
    expect(rememberPendingInvite('TEAM123456', 1_000)).toBe('TEAM123456')
    expect(peekPendingInvite(1_001)).toBe('TEAM123456')
  })

  it('邀请码只能消费一次，超过 15 分钟自动失效', () => {
    rememberPendingInvite('TEAM123456', 1_000)
    expect(consumePendingInvite(1_001)).toBe('TEAM123456')
    expect(consumePendingInvite(1_002)).toBe('')
    rememberPendingInvite('TEAM654321', 1_000)
    expect(peekPendingInvite(1_000 + 16 * 60 * 1_000)).toBe('')
  })

  it('支持分享路径 query 和二维码 scene', () => {
    expect(rememberLaunchInvite({ scene: 1007, query: { code: 'TEAM123456' } })).toBe('TEAM123456')
    expect(rememberLaunchInvite({ scene: 1047, query: { scene: 'invite%3DTEAM654321' } })).toBe('TEAM654321')
  })
  it('分享加入页加载不会抢先消费邀请码，未验证账号不请求项目预览', () => {
    rememberLaunchInvite({ scene: 1007, query: { code: 'TEAM123456' } })
    const source = readFileSync('src/pages/project/join.vue', 'utf8')
    const onLoadBlock = source.match(/onLoad\(\(query\) => \{[\s\S]*?\n\}\)/)?.[0] || ''
    expect(onLoadBlock).toContain('inviteCodeForJoinPage(query)')
    expect(onLoadBlock).not.toContain('rememberPendingInvite')
    expect(inviteCodeForJoinPage({ code: 'TEAM123456' })).toBe('TEAM123456')
    expect(onLoadBlock).not.toContain('consumePendingInvite')
    expect(peekPendingInvite()).toBe('TEAM123456')
    const previewBlock = source.slice(source.indexOf('async function loadPreview'), source.indexOf('watch(code'))
    expect(previewBlock.indexOf("sessionState.stage !== 'authenticated'")).toBeLessThan(previewBlock.indexOf('mobileApi.previewProjectInvite'))
  })

  it.each([1001, 1023, 1089, 1090])('正常打开场景 %s 不重放微信恢复的旧路径和邀请码', (scene) => {
    rememberPendingInvite('LPRVSFTCST')
    expect(rememberLaunchInvite({ scene, path: 'pages/project/join', query: { code: 'LPRVSFTCST' } }, 'launch')).toBe('')
    expect(peekPendingInvite()).toBe('')
    expect(inviteCodeForJoinPage({ code: 'LPRVSFTCST' })).toBe('')
    expect(isDiscardedInviteEntry()).toBe(true)
  })

  it('同一次分享的 launch/show 和重复前台事件不刷新 15 分钟期限', () => {
    const entry = { scene: 1007, path: 'pages/project/join', query: { code: 'TEAM123456' } }
    expect(rememberLaunchInvite(entry, 'launch', 1_000)).toBe('TEAM123456')
    expect(rememberLaunchInvite(entry, 'show', 2_000)).toBe('TEAM123456')
    expect(rememberLaunchInvite(entry, 'show', 800_000)).toBe('TEAM123456')
    expect(peekPendingInvite(902_000)).toBe('')
    expect(rememberLaunchInvite(entry, 'show', 902_001)).toBe('')
  })

  it('成功入项或提交审批后不再重放相同邀请，但另一个账号可打开新的分享', () => {
    storage.set('engineering-image:account:v1', { id: 'approved-member' })
    const entry = { scene: 1007, path: 'pages/project/join', query: { code: 'TEAM123456' } }
    rememberLaunchInvite(entry, 'launch')
    consumePendingInvite()
    expect(rememberLaunchInvite(entry, 'show')).toBe('')
    expect(rememberLaunchInvite(entry, 'launch')).toBe('')
    expect(isHandledLaunchInvite('TEAM123456')).toBe(true)
    storage.set('engineering-image:account:v1', { id: 'new-applicant' })
    expect(rememberLaunchInvite(entry, 'launch')).toBe('TEAM123456')
  })

  it('明确失效邀请不会因再次打开旧分享卡片而恢复，手动输入新码仍可申请', () => {
    invalidatePendingInvite('LPRVSFTCST')
    expect(rememberLaunchInvite({ scene: 1008, query: { code: 'LPRVSFTCST' } })).toBe('')
    expect(rememberPendingInvite('TEAM654321')).toBe('TEAM654321')
    expect(inviteCodeForJoinPage({ code: 'TEAM654321' })).toBe('TEAM654321')
  })

  it('普通切后台回来保留当前主动填写的邀请，坏 scene 编码不会抛异常', () => {
    rememberPendingInvite('TEAM654321')
    expect(rememberLaunchInvite({ scene: 1001, path: 'pages/project/join' }, 'show')).toBe('')
    expect(peekPendingInvite()).toBe('TEAM654321')
    expect(isDiscardedInviteEntry()).toBe(false)
    expect(() => rememberLaunchInvite({ scene: 1047, query: { scene: '%invalid' } })).not.toThrow()
  })

  it('App 使用实际 onAppShow 参数，不再重复读取上一次 getEnterOptionsSync', () => {
    const app = readFileSync('src/App.vue', 'utf8')
    expect(app).toContain('onAppShow((options) =>')
    expect(app).toContain("rememberLaunchInvite(options, 'show')")
    expect(app).not.toContain('getEnterOptionsSync')
  })

})
