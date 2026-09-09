import { beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { consumePendingInvite, normalizeInviteCode, peekPendingInvite, rememberLaunchInvite, rememberPendingInvite } from '@/services/pending-invite'

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
    expect(rememberLaunchInvite({ query: { code: 'TEAM123456' } })).toBe('TEAM123456')
    expect(rememberLaunchInvite({ query: { scene: 'invite%3DTEAM654321' } })).toBe('TEAM654321')
  })
  it('分享加入页加载不会抢先消费邀请码，未验证账号不请求项目预览', () => {
    rememberLaunchInvite({ query: { code: 'TEAM123456' } })
    const source = readFileSync('src/pages/project/join.vue', 'utf8')
    const onLoadBlock = source.match(/onLoad\(\(query\) => \{[\s\S]*?\n\}\)/)?.[0] || ''
    expect(onLoadBlock).toContain('peekPendingInvite()')
    expect(onLoadBlock).toContain('rememberPendingInvite(code.value)')
    expect(onLoadBlock).not.toContain('consumePendingInvite')
    expect(peekPendingInvite()).toBe('TEAM123456')
    const previewBlock = source.slice(source.indexOf('async function loadPreview'), source.indexOf('watch(code'))
    expect(previewBlock.indexOf("sessionState.stage !== 'authenticated'")).toBeLessThan(previewBlock.indexOf('mobileApi.previewProjectInvite'))
  })

})
