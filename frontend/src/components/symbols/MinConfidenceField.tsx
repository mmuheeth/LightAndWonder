import { Input } from '@/components/ui/input'
import type { MinConfidence } from '@/hooks/useMinConfidence'

/** The percent a tile must reach to be named, as a field. Say what depends on it in `title`. */
export function MinConfidenceField({ minConfidence, title }: { minConfidence: MinConfidence; title: string }) {
  return (
    <label className="space-y-1 text-xs text-muted-foreground" title={title}>
      Min confidence (%)
      <Input
        value={minConfidence.text}
        onChange={(event) => minConfidence.change(event.target.value)}
        onBlur={minConfidence.settle}
        inputMode="decimal"
        autoComplete="off"
        aria-invalid={minConfidence.invalid}
        className="block w-24 text-foreground"
      />
    </label>
  )
}
