export const API_MODE: 'real' | 'mock' = import.meta.env.VITE_API_MODE === 'mock' ? 'mock' : 'real'
export const BUILD_CHANNEL = API_MODE === 'mock' ? '__ENGINEERING_API_MOCK__' : '__ENGINEERING_API_REAL__'
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'https://api.shuiliyingxiang.cn').replace(/\/$/, '')
export const WECHAT_APP_ID = import.meta.env.VITE_WECHAT_APP_ID || ''

export const CURRENT_PROJECT = {
  id: 'default',
  name: '邯郸市永年区洺河龙泉缓洪工程',
  code: 'YNLQ',
} as const
