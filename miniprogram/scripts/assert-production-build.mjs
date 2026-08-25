import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const output = resolve('dist/build/mp-weixin')
const requiredTabBarFiles = ['index.js', 'index.json', 'index.wxml', 'index.wxss']
for (const file of requiredTabBarFiles) {
  const target = join(output, 'custom-tab-bar', file)
  if (!existsSync(target)) throw new Error(`微信原生 custom-tab-bar 构建缺失：${target}`)
}

function collectFiles(directory) {
  return readdirSync(directory).flatMap((name) => {
    const target = join(directory, name)
    return statSync(target).isDirectory() ? collectFiles(target) : [target]
  })
}

const files = collectFiles(output)
const forbiddenFiles = files.filter((file) => /(^|[\\/])mock\.js$/i.test(file))
if (forbiddenFiles.length) throw new Error(`微信正式构建混入 Mock 模块：${forbiddenFiles.join(', ')}`)
const javascript = files.filter((file) => file.endsWith('.js'))
const bundle = javascript.map((file) => readFileSync(file, 'utf8')).join('\n')
if (!bundle.includes('__ENGINEERING_API_REAL__')) throw new Error('微信构建缺少 real API 标记，禁止发布')
if (bundle.includes('__ENGINEERING_API_MOCK__')) throw new Error('微信构建混入 mock API 标记，禁止发布')
for (const marker of ['mockRequest', 'mockUpload', 'samplePhotos']) {
  if (bundle.includes(marker)) throw new Error(`微信正式构建混入 Mock 样例标识：${marker}`)
}
const projectConfig = JSON.parse(readFileSync(join(output, 'project.config.json'), 'utf8'))
if (!projectConfig.libVersion || Number(projectConfig.libVersion.split('.')[0]) < 2 || (projectConfig.libVersion.startsWith('2.') && Number(projectConfig.libVersion.split('.')[1]) < 25)) {
  throw new Error('微信基础库必须为 2.25.0 或更高，才能一次选择 20 张照片')
}
if (!Array.isArray(projectConfig.packOptions?.include)) {
  throw new Error('微信项目配置缺少 packOptions.include，开发者工具会反复改写发布目录')
}
for (const key of ['compileWorklet', 'uglifyFileName', 'uploadWithSourceMap', 'minifyWXSS', 'minifyWXML']) {
  if (!(key in (projectConfig.setting || {}))) {
    throw new Error(`微信项目配置缺少 ${key}，开发者工具会反复改写发布目录`)
  }
}
if (!existsSync(join(output, '.gitignore')) || !readFileSync(join(output, '.gitignore'), 'utf8').includes('project.private.config.json')) {
  throw new Error('微信发布目录必须忽略 project.private.config.json，禁止提交本机私有设置')
}
if (process.env.REQUIRE_WECHAT_APP_ID === '1') {
  if (!projectConfig.appid || projectConfig.appid === 'touristappid') throw new Error('正式体验版缺少 VITE_WECHAT_APP_ID，禁止发布')
}
console.log('发布检查通过：real API、无 Mock 模块 + 微信原生 custom-tab-bar 四文件完整')
