export interface HealthCheck {
  status: string
  app_name: string
  app_version: string
  app_env: string
  uptime_seconds: number
}
