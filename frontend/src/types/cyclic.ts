import type { GameMode } from '@/types/gameContext'
import type { RoiImage } from '@/types/roi'

/**
 * How a message area's capture ended. `closed`: a message came round again, so the whole cycle was seen.
 * `steady`: after the game went idle it kept showing the same thing (one message, or none). `open`: the capture
 * ended before either, so the area may have had more messages.
 */
export type CycleState = 'open' | 'closed' | 'steady'

export type CyclicEventType = 'result' | 'first_cycle_done' | 'cycle_stopped' | 'game_over'

/**
 * Why a round stopped being captured. `complete`: every area was seen to cycle or hold steady. `next_spin`: the next
 * spin began first. `timeout`: it took longer than the limit. `stopped`: tracking was stopped. `interrupted`: the
 * backend stopped while it was being captured.
 */
export type EndReason = 'complete' | 'next_spin' | 'timeout' | 'stopped' | 'interrupted'

/**
 * `waiting`: for a spin. `spinning`: the reels are turning. `capturing`: screenshots are being taken.
 */
export type TrackingPhase = 'stopped' | 'waiting' | 'spinning' | 'capturing'

/** One distinct message a message area showed. */
export interface CyclicMessage extends RoiImage {
  /** Position among the area's messages, in the order they were first seen. */
  index: number
  /** Seconds after the reels stopped that it first appeared. */
  first_seen: number
  /** How many times it was shown (more than once when the area cycled). */
  appearances: number
  /** What the OCR read. Null until it has; empty when it found no text. */
  text: string | null
  confidence: number | null
  /** Set when the OCR could not read it. */
  read_error: string | null
}

export interface CyclicRegion {
  /** The game config key: `cyclic_message` or `cyclic_message_2`. */
  name: string
  /** Where it was cut: [left, top, right, bottom] as fractions of the screenshot. */
  roi: number[]
  messages: CyclicMessage[]
  /** The messages in the order they were shown, as indexes into `messages`: [0, 1, 2, 0, 1, 2] for a cycle of three. */
  sequence: number[]
  cycle: CycleState
}

/** Something the game's log said about the spin, placed on the capture's clock. */
export interface CyclicEvent {
  type: CyclicEventType
  /** Seconds after the reels stopped. */
  at: number
  log_time: string | null
}

/** What the message areas showed after one spin, from the moment its reels stopped. */
export interface CyclicRound {
  id: string
  /** When the spin started. */
  created_at: string
  game: string
  mode: GameMode
  /** From the log's result line; null until it has been seen. */
  won: boolean | null
  /** The win in the game's smallest currency unit (400 is $4.00), as the log writes it. */
  win_amount: number | null
  events: CyclicEvent[]
  regions: CyclicRegion[]
  /** How many screenshots were taken. */
  frames: number
  /** How long the capture ran, in seconds after the reels stopped. */
  seconds: number
  /** Null while the round is being captured. */
  end_reason: EndReason | null
}

export interface CyclicStatus {
  tracking: boolean
  game: string
  mode: GameMode
  phase: TrackingPhase
  /** Spins seen since tracking started. */
  rounds: number
  /** The round being captured, as far as it has got. */
  current: CyclicRound | null
  log_path: string | null
  /** The log cannot be read, so no spin will be noticed. */
  log_unreadable: boolean
  /** What is wrong right now, e.g. OBS refusing screenshots. */
  problem: string | null
  /** The OCR models are loaded. */
  ocr_ready: boolean
}
