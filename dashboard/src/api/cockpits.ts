import { apiGet } from './client'
import type { CfoCockpitData } from '../types/cfo'

export function getCfoCockpit(): Promise<CfoCockpitData> {
  return apiGet<CfoCockpitData>('/cockpits/cfo')
}
