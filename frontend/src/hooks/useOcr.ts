import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { extractOcr, fetchOcrRecords, readOcrRecord, warmUpOcr } from '@/api/ocr'
import type { GameContext } from '@/types/gameContext'
import type { OcrRecord } from '@/types/ocr'

const RECORDS_KEY = ['ocr', 'records']

/**
 * Opening the OCR tab starts loading the OCR models on the backend (about half a minute), so they are ready
 * by the time Extract Values is pressed. Asking again is harmless, and a failure only means the first read
 * loads them itself.
 */
export function useWarmUpOcr() {
  useEffect(() => {
    warmUpOcr().catch(() => undefined)
  }, [])
}

/** The newest record only; it is the one the tab shows. */
export function useLatestOcrRecord() {
  return useQuery({
    queryKey: RECORDS_KEY,
    queryFn: () => fetchOcrRecords(1),
    select: (records) => records[0] ?? null,
  })
}

/** The one record the tab shows is replaced by the new one, without another round trip. */
function useShowRecord() {
  const queryClient = useQueryClient()
  return (record: OcrRecord) => queryClient.setQueryData<OcrRecord[]>(RECORDS_KEY, [record])
}

type ExtractPhase = 'capturing' | 'reading'

/**
 * Extract Values: captures and crops the meter and messages, then reads them. The crops are shown as soon as
 * they exist, while the (slower) reading is still going on, so `phase` says which step it is at. If the
 * reading fails the crops stay, and `useReadOcrRecord` can try again.
 */
export function useExtractValues() {
  const show = useShowRecord()
  const [phase, setPhase] = useState<ExtractPhase | null>(null)
  const mutation = useMutation({
    mutationFn: async (context: GameContext) => {
      setPhase('capturing')
      const captured = await extractOcr(context)
      show(captured)
      setPhase('reading')
      return readOcrRecord(captured.id)
    },
    onSuccess: show,
    onSettled: () => setPhase(null),
  })
  return { ...mutation, phase }
}

/** Reads a record that has no readings yet (or whose reading failed), or reads it again. */
export function useReadOcrRecord() {
  const show = useShowRecord()
  return useMutation({ mutationFn: readOcrRecord, onSuccess: show })
}
