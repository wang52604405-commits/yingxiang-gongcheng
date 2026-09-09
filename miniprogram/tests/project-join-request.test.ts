import { beforeEach, describe, expect, it } from 'vitest'
import { clearJoinRequest, normalizeJoinRequest, pendingJoinRequest, rememberJoinRequest, validateJoinApplicant } from '@/services/project-join-request'

beforeEach(() => {
  const data = new Map<string, unknown>()
  ;(globalThis as any).uni = { getStorageSync: (key: string) => data.get(key), setStorageSync: (key: string, value: unknown) => data.set(key, value), removeStorageSync: (key: string) => data.delete(key) }
})
describe('applicant details and approval state', () => {
  it('requires a real-name field and a valid mainland mobile number before submitting', () => {
    expect(validateJoinApplicant('', '13812345678')).toContain('姓名')
    expect(validateJoinApplicant('张三', '')).toContain('手机号')
    expect(validateJoinApplicant('张三', '12345678901')).toContain('手机号')
    expect(validateJoinApplicant('张三', '138123456789')).toContain('手机号')
    expect(validateJoinApplicant(' 张三 ', '13812345678')).toBe('')
  })
  it('normalizes terminal and pending states without treating unknown states as approved', () => {
    for (const status of ['pending', 'approved', 'rejected', 'expired', 'revoked']) {
      expect(normalizeJoinRequest({ id: 12, status, applicant_account_id: 42 })?.applicant_account_id).toBe('42')
    }
    expect(normalizeJoinRequest({ id: 'x', status: 'unknown' })).toBeUndefined()
    expect(normalizeJoinRequest({ status: 'approved' })).toBeUndefined()
  })
  it('keeps return-to-request state isolated by account and does not store contact details', () => {
    rememberJoinRequest('one', 'req-1')
    expect(pendingJoinRequest('one')).toBe('req-1')
    expect(pendingJoinRequest('two')).toBe('')
    clearJoinRequest('two')
    expect(pendingJoinRequest('one')).toBe('req-1')
    clearJoinRequest('one')
    expect(pendingJoinRequest('one')).toBe('')
  })
})
