import { describe, expect, it } from 'vitest'
import { canTransition, recoverInterruptedStatus, transitionPhoto } from '@/services/photo-state'

describe('照片状态机', () => {
  it('只允许契约定义的正向状态变化', () => {
    expect(canTransition('local_ready', 'uploading')).toBe(true)
    expect(canTransition('uploading', 'server_saved')).toBe(true)
    expect(canTransition('server_saved', 'analyzing')).toBe(true)
    expect(canTransition('analyzing', 'needs_review')).toBe(true)
    expect(canTransition('needs_review', 'desktop_pending')).toBe(true)
    expect(canTransition('desktop_pending', 'desktop_imported')).toBe(true)
    expect(() => transitionPhoto('local_ready', 'desktop_imported')).toThrow('非法照片状态变化')
  })

  it('小程序被中断后不能把上传中误显示为成功', () => {
    expect(recoverInterruptedStatus('uploading')).toBe('local_ready')
    expect(recoverInterruptedStatus('server_saved')).toBe('server_saved')
  })
})
