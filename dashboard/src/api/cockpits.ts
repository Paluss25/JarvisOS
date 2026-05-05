import { apiGet } from './client'
import type { CioCockpitData } from '../types/cio'
import type { CfoCockpitData } from '../types/cfo'

export function getCfoCockpit(): Promise<CfoCockpitData> {
  return apiGet<CfoCockpitData>('/cockpits/cfo')
}

export function getCioCockpit(): Promise<CioCockpitData> {
  return apiGet<CioCockpitData>('/cockpits/cio')
}
