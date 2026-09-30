import type { GameMode } from '@/types/gameContext'

export interface GafStatus {
  game: string
  mode: GameMode
  /** Where NRobot listens. */
  nrobot_url: string
  /** `host:port` of the game in this mode; null if the game has no GAF config. */
  target: string | null
  /** NRobot answers and has its keyword libraries loaded. */
  reachable: boolean
  /** There is a live session to the selected game in the selected mode. */
  connected: boolean
  /** The game's idle state machine, while connected (e.g. `stateIdleWithCredits`). */
  state: string | null
  /** Why it is not reachable or connected, or what is wrong with the game's GAF config. */
  detail: string | null
  /** What holds the game connection right now (e.g. `Spin`); other requests wait or are refused. */
  busy: string | null
}

/** An input an action takes, described so the UI can offer it without knowing the action. */
export interface GafActionParam {
  name: string
  label: string
  kind: 'choice' | 'number'
  default: string | number
  /** For `choice`: what may be picked. */
  options: string[]
  /** For `number`: the range. */
  min: number | null
  max: number | null
}

/** What an action is run with, by parameter name. */
export type GafActionInputs = Record<string, string | number>

export interface GafActionInfo {
  id: string
  label: string
  description: string
  /** `common` actions exist for every game; `game` ones only where the game's config lists them. */
  scope: 'common' | 'game'
  params: GafActionParam[]
}

export interface GafActionResult {
  action: string
  label: string
  /** One line for a person, e.g. "Spin settled after 6.2s". */
  message: string
  /** What the action read or did, by name. */
  values: Record<string, string | string[]>
}
