import { useParams } from 'react-router-dom'
import CockpitShell from '../components/cockpits/CockpitShell'
import { getCockpitConfig } from '../cockpits/registry'
import CfoCockpitPage from './CfoCockpitPage'
import CioCockpitPage from './CioCockpitPage'

export default function CockpitPage() {
  const { id } = useParams()

  if (id === 'cfo') {
    return <CfoCockpitPage />
  }

  if (id === 'cio') {
    return <CioCockpitPage />
  }

  const config = id ? getCockpitConfig(id) : null

  if (!config) {
    return <main className="ops-page empty-state">No cockpit configured for this agent.</main>
  }

  return <CockpitShell config={config} />
}
