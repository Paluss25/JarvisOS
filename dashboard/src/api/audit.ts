import { apiGet } from './client'
import type { AuditContext, AuditResponse } from '../types/audit'

export function listAudit(params: URLSearchParams): Promise<AuditResponse> {
  return apiGet<AuditResponse>(`/audit?${params}`)
}

export function getAuditContext(id: string | number): Promise<AuditContext> {
  return apiGet<AuditContext>(`/audit/${id}`)
}
