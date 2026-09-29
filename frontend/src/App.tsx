import { HealthStatus } from '@/components/HealthStatus'

function App() {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6">
      <h1 className="font-heading text-2xl font-medium">Light & Wonder</h1>
      <p className="text-sm text-muted-foreground">
        Frontend ↔ backend integration check
      </p>
      <HealthStatus />
    </div>
  )
}

export default App
