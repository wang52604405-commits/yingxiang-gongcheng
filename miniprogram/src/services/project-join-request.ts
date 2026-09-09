export interface ProjectJoinRequest {
  id: string
  status: 'pending' | 'approved' | 'rejected' | 'expired' | 'revoked'
  project_id: string
  project_name: string
  display_name: string
  phone: string
  applicant_account_id: string
  approver_account_id: string
  created_at: string
  role: string
  can_review: boolean
  reason?: string
}
export function normalizeJoinRequest(raw: any): ProjectJoinRequest | undefined {
  if (!raw?.id || !['pending', 'approved', 'rejected', 'expired', 'revoked'].includes(raw.status)) return undefined
  return { id: String(raw.id), status: raw.status, project_id: String(raw.project_id || ''), project_name: String(raw.project_name || ''), display_name: String(raw.display_name || ''), phone: String(raw.phone || ''), applicant_account_id: String(raw.applicant_account_id || ''), approver_account_id: String(raw.approver_account_id || ''), created_at: String(raw.created_at || ''), role: String(raw.role || ''), can_review: Boolean(raw.can_review), reason: String(raw.reason || raw.rejection_reason || '') }
}
export function validateJoinApplicant(name: string, phone: string): string {
  if (!name.trim() || name.trim().length > 60) return '请填写真实姓名，最多 60 个字'
  if (!/^1[3-9]\d{9}$/.test(phone.trim())) return '请输入正确的 11 位手机号'
  return ''
}
const key = (owner: string | number) => `engineering-image:pending-join-request:v1:account:${encodeURIComponent(String(owner))}`
export function rememberJoinRequest(owner: string | number, requestId: string): void { uni.setStorageSync(key(owner), requestId) }
export function pendingJoinRequest(owner: string | number): string { return String(uni.getStorageSync(key(owner)) || '') }
export function clearJoinRequest(owner: string | number): void { uni.removeStorageSync(key(owner)) }
