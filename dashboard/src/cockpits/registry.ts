import type { CockpitConfig } from '../types/cockpit'
import { cfoCockpit } from './cfo'
import { cioCockpit } from './cio'
import { cisoCockpit } from './ciso'

export const cockpitRegistry: Record<string, CockpitConfig> = {
  cfo: cfoCockpit,
  cio: cioCockpit,
  ciso: cisoCockpit,
}

export function getCockpitConfig(agentId: string): CockpitConfig | null {
  return cockpitRegistry[agentId] ?? null
}
