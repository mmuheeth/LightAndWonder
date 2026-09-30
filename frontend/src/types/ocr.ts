import type { GameMode } from '@/types/gameContext'
import type { ObsScreenshot } from '@/types/obs'
import type { RoiImage } from '@/types/roi'

/** One image the OCR reads, cut out of a screenshot. */
export interface OcrCrop extends RoiImage {
  /**
   * `credit_meter` / `cash_meter`: the meter region while the game showed that meter. `meter`: the meter
   * region when which meter it showed was not known. `cyclic_message` and `cyclic_message_2`.
   */
  name: string
  /** Where it was cut: [left, top, right, bottom] as fractions of the screenshot. */
  roi: number[]
}

/** One amount of a meter; nothing is set when the meter showed none (e.g. no win). */
export interface AmountRead {
  /** As the game shows it: "$1,039.55", "99720". */
  text: string | null
  /** The number in `text`, without the currency symbol and thousands separators. */
  value: number | null
  /** Percent the recognizer was sure of the text. */
  confidence: number | null
}

interface MeterFields {
  /** Often empty: the game shows no win most of the time. */
  win: AmountRead
  bet: AmountRead
  /** What looked wrong: a required amount that was not found, or one read with little confidence. */
  issues: string[]
}

/** The meter while it counts in credits. */
export interface CreditMeterReading extends MeterFields {
  credits: AmountRead
}

/** The meter while it counts in currency. */
export interface CashMeterReading extends MeterFields {
  cash: AmountRead
}

export interface TextRead {
  /** Empty when the message area showed nothing. */
  text: string
  confidence: number | null
}

export interface OcrReadings {
  read_at: string
  /** How long the OCR took. */
  seconds: number
  /** Null when that meter was not captured. */
  credit_meter: CreditMeterReading | null
  cash_meter: CashMeterReading | null
  /** Null when the game has no such message area. */
  cyclic_message: TextRead | null
  cyclic_message_2: TextRead | null
  /** What went wrong with no meter to blame. */
  issues: string[]
}

export interface OcrEngineStatus {
  /** The OCR models are loaded, so a read starts at once. Until then a read waits for them. */
  ready: boolean
}

export interface OcrRecord {
  id: string
  created_at: string
  game: string
  mode: GameMode
  /** What the crops were cut from: the meter as found, then (when it could be toggled) the other one. */
  screenshots: ObsScreenshot[]
  crops: OcrCrop[]
  /** Worth telling the person: why only one meter was captured, or that the meter was left toggled. */
  notes: string[]
  /** Null until the record has been read. */
  readings: OcrReadings | null
}
