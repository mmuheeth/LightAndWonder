export type GameMode = 'simulator' | 'egm'

export interface GameContext {
  game: string
  mode: GameMode
}

export interface GameContextOptions {
  games: string[]
  modes: GameMode[]
}

export interface GameContextResponse {
  context: GameContext
  options: GameContextOptions
}

export type GameContextUpdate = Partial<GameContext>
