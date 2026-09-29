import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { extractRoi, fetchRoiRecords } from '@/api/roi'
import type { RoiRecord } from '@/types/roi'

/** How many earlier extractions the ROI tab lists, below the newest one. */
const PREVIOUS_ROI_RECORD_COUNT = 5

const RECORDS_KEY = ['roi', 'records']
// The newest record is shown on its own, so one more than the earlier ones is loaded.
const LOADED_COUNT = PREVIOUS_ROI_RECORD_COUNT + 1

/** Newest first; kept on the backend, so it is the same after a page refresh. */
export function useRoiRecords() {
  return useQuery({
    queryKey: RECORDS_KEY,
    queryFn: () => fetchRoiRecords(LOADED_COUNT),
  })
}

/** The new record goes straight to the top of the list, without another round trip. */
export function useExtractRoi() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: extractRoi,
    onSuccess: (record) =>
      queryClient.setQueryData<RoiRecord[]>(RECORDS_KEY, (records = []) =>
        [record, ...records.filter((other) => other.id !== record.id)].slice(0, LOADED_COUNT),
      ),
  })
}
