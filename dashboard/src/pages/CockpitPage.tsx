import { useParams } from 'react-router-dom'
import CockpitShell from '../components/cockpits/CockpitShell'
import { getCockpitConfig } from '../cockpits/registry'

export default function CockpitPage() {
  const { id } = useParams()
  const config = id ? getCockpitConfig(id) : null

  if (!config) {
    return <main className="ops-page empty-state">No cockpit configured for this agent.</main>
  }

  return <CockpitShell config={config} />
}
