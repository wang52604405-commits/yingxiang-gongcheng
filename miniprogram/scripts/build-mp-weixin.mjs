import { readFileSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const uniCli = resolve('node_modules/@dcloudio/vite-plugin-uni/bin/uni.js')
const built = spawnSync(process.execPath, [uniCli, 'build', '-p', 'mp-weixin'], {
  cwd: process.cwd(),
  env: { ...process.env, VITE_API_MODE: 'real' },
  stdio: 'inherit',
})
if (built.error) throw built.error
if (built.status !== 0) process.exit(built.status || 1)

const appId = String(process.env.VITE_WECHAT_APP_ID || '').trim()
const configPath = resolve('dist/build/mp-weixin/project.config.json')
const config = JSON.parse(readFileSync(configPath, 'utf8'))
config.libVersion = config.libVersion || '2.25.0'
if (appId) config.appid = appId
writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8')

await import('./assert-production-build.mjs')
