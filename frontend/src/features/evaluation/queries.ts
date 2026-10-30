import { useQuery } from '@tanstack/react-query'
import { getBadcases, getSummary } from '../../api/series'

export function useSummary() {
  return useQuery({ queryKey: ['summary'], queryFn: getSummary })
}

export function useBadcases(seriesId: string | undefined) {
  return useQuery({
    queryKey: ['badcases', seriesId],
    queryFn: () => getBadcases(seriesId!),
    enabled: Boolean(seriesId),
  })
}
