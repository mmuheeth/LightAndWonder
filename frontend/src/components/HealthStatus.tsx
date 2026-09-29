import { useEffect } from 'react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useHealthCheck } from '@/hooks/useHealthCheck'
import { useConnectionStore } from '@/store/useConnectionStore'

export function HealthStatus() {
  const { data, error, isLoading, isFetching, dataUpdatedAt } = useHealthCheck()
  const setStatus = useConnectionStore((state) => state.setStatus)

  useEffect(() => {
    setStatus(Boolean(data) && !error)
  }, [data, error, setStatus])

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Backend Health
          {isLoading ? (
            <Badge variant="secondary">checking…</Badge>
          ) : error ? (
            <Badge variant="destructive">unreachable</Badge>
          ) : (
            <Badge className="bg-green-600 text-white">{data?.status}</Badge>
          )}
        </CardTitle>
        <CardDescription>
          {import.meta.env.VITE_API_BASE_URL}/health
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {error ? (
          <p className="text-destructive">{error.message}</p>
        ) : data ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
            <dt className="text-muted-foreground">App</dt>
            <dd>{data.app_name}</dd>
            <dt className="text-muted-foreground">Version</dt>
            <dd>{data.app_version}</dd>
            <dt className="text-muted-foreground">Environment</dt>
            <dd>{data.app_env}</dd>
            <dt className="text-muted-foreground">Uptime</dt>
            <dd>{data.uptime_seconds}s</dd>
          </dl>
        ) : null}
        {dataUpdatedAt ? (
          <p className="text-xs text-muted-foreground">
            Last checked {new Date(dataUpdatedAt).toLocaleTimeString()}
            {isFetching ? ' · refreshing…' : ''}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}
