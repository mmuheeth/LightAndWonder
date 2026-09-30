import { useState } from 'react'

// One setting for the Symbol and Payline tabs: a tile is read the same way in both.
const STORAGE_KEY = 'symbols.minConfidence'
// Only until the backend's own default (its SYMBOL_MIN_CONFIDENCE setting) has arrived.
const FALLBACK_MIN_CONFIDENCE = 90

/** A percent from 0 to 100, or null. */
function parsePercent(raw: string): number | null {
  const value = Number(raw)
  return raw.trim() !== '' && Number.isFinite(value) && value >= 0 && value <= 100 ? value : null
}

function storedMinConfidence(): number | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw === null ? null : parsePercent(raw)
  } catch {
    return null // storage can be blocked; the threshold then just is not remembered
  }
}

export interface MinConfidence {
  /** The percent in force. */
  value: number
  /** What the field shows: what is being typed, else the value. */
  text: string
  /** What is being typed is not a percent, so it is not applied. */
  invalid: boolean
  change: (raw: string) => void
  /** Leaves what is typed behind, back to the value in force. */
  settle: () => void
}

/**
 * The confidence a tile must reach to be named. It starts at the backend's default, and what the user
 * sets is remembered in this browser. It applies to the reading on screen at once, without a new screenshot.
 */
export function useMinConfidence(backendDefault: number | undefined): MinConfidence {
  const [chosen, setChosen] = useState<number | null>(storedMinConfidence)
  // What is in the field, while it is being typed: it may be unfinished, and then is not applied.
  const [draft, setDraft] = useState<string | null>(null)

  const value = chosen ?? backendDefault ?? FALLBACK_MIN_CONFIDENCE
  const invalid = draft !== null && parsePercent(draft) === null

  const change = (raw: string) => {
    setDraft(raw)
    const percent = parsePercent(raw)
    if (percent === null) return
    setChosen(percent)
    try {
      localStorage.setItem(STORAGE_KEY, String(percent))
    } catch {
      // not remembered
    }
  }

  return { value, text: draft ?? String(value), invalid, change, settle: () => setDraft(null) }
}
