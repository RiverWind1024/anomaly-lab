import { useQuery } from '@tanstack/react-query'
import { getAlerts } from '../../api/platform'

export interface AlertFilters {
  jobId?: number
  level?: string
  seriesId?: string
  since?: string
  until?: string
}

export const alertsKey = ['alerts'] as const

export function useAlerts(filters: AlertFilters) {
  return useQuery({
    queryKey: [...alertsKey, filters],
    queryFn: () => getAlerts(filters),
  })
}
