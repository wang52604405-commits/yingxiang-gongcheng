import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

function source(path: string): string {
  return readFileSync(resolve(path), 'utf8')
}

describe('微信正式包 Mock 物理隔离', () => {
  it('真实 API 客户端不静态引用样例模块，构建 alias 决定唯一运行时', () => {
    const client = source('src/api/client.ts')
    const realRuntime = source('src/api/runtime-real.ts')
    const config = source('vite.config.ts')
    expect(client).not.toContain("from './mock'")
    expect(client).not.toContain('mockRequest')
    expect(client).not.toContain('mockUpload')
    expect(realRuntime).not.toContain("from './mock'")
    expect(config).toContain("'@api-runtime'")
    expect(config).toContain('runtime-real.ts')
    expect(config).toContain('runtime-mock.ts')
  })

  it('发布断言递归拒绝 mock.js、Mock 函数和 samplePhotos', () => {
    const assertion = source('scripts/assert-production-build.mjs')
    expect(assertion).toContain('mock\\.js')
    expect(assertion).toContain('mockRequest')
    expect(assertion).toContain('mockUpload')
    expect(assertion).toContain('samplePhotos')
  })
})
