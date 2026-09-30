import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useUpdateGameContext } from '@/hooks/useGameContext'
import { useGameContextStore } from '@/store/useGameContextStore'
import type { GameMode } from '@/types/gameContext'

const MODE_LABELS: Record<GameMode, string> = {
  simulator: 'Simulator',
  egm: 'EGM',
}

export function GameContextSelectors() {
  const context = useGameContextStore((state) => state.context)
  const options = useGameContextStore((state) => state.options)
  const { mutate, isPending } = useUpdateGameContext()

  const disabled = !context || isPending

  return (
    <div className="flex shrink-0 items-center gap-2">
      <Select
        value={context?.game ?? ''}
        onValueChange={(game) => mutate({ game })}
        disabled={disabled}
      >
        <SelectTrigger aria-label="Game" className="w-36 sm:w-48">
          <SelectValue placeholder="Select game" />
        </SelectTrigger>
        <SelectContent align="end">
          {options.games.map((game) => (
            <SelectItem key={game} value={game}>
              {game}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={context?.mode ?? ''}
        onValueChange={(mode) => mutate({ mode: mode as GameMode })}
        disabled={disabled}
      >
        <SelectTrigger aria-label="Game mode" className="w-28 sm:w-32">
          <SelectValue placeholder="Select mode" />
        </SelectTrigger>
        <SelectContent align="end">
          {options.modes.map((mode) => (
            <SelectItem key={mode} value={mode}>
              {MODE_LABELS[mode]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
