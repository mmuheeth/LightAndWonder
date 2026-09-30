import { Dumbbell, Loader2, RefreshCw } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useSymbolModel, useTrainSymbolModel } from '@/hooks/useSymbols'
import { useGameContextStore } from '@/store/useGameContextStore'

function StateBadge({ state, unavailable, progress }: {
  state: string | undefined
  unavailable: boolean
  progress: string | null
}) {
  if (unavailable) return <Badge variant="destructive">unavailable</Badge>
  switch (state) {
    case 'ready':
      return <Badge variant="secondary">ready</Badge>
    case 'training':
      return (
        <Badge variant="secondary">
          <Loader2 className="animate-spin" />
          {progress ?? 'training'}
        </Badge>
      )
    case 'failed':
      return <Badge variant="destructive">failed</Badge>
    case 'untrained':
      return <Badge variant="outline">not trained</Badge>
    default:
      return <Badge variant="outline">…</Badge>
  }
}

export function SymbolTrainingCard() {
  const context = useGameContextStore((state) => state.context)
  const status = useSymbolModel(context?.game)
  const train = useTrainSymbolModel()

  const model = status.data
  const training = model?.state === 'training'
  const progress = model?.progress
  const hasArtwork = (model?.dataset_classes ?? 0) >= 2

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Dumbbell className="size-4" />
          Training
        </CardTitle>
        <CardDescription className="max-w-3xl">
          Fits ResNet34 to the symbol artwork. A few minutes on this machine — it runs on the CPU, on half the
          cores, so the rest of the dashboard keeps working while it does.
        </CardDescription>
        <CardAction className="flex items-center gap-2">
          <StateBadge
            state={model?.state}
            unavailable={status.isError}
            progress={progress && progress.epoch > 0 ? `epoch ${progress.epoch}/${progress.epochs}` : null}
          />
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Refresh training status"
            title="Refresh"
            onClick={() => status.refetch()}
            disabled={!context || status.isFetching}
          >
            <RefreshCw className={status.isFetching ? 'animate-spin' : undefined} />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button
          variant="outline"
          onClick={() => context && train.mutate(context.game)}
          disabled={!context || !hasArtwork || training || train.isPending}
        >
          {training || train.isPending ? <Loader2 className="animate-spin" /> : <Dumbbell />}
          Train
        </Button>

        {model ? (
          <p className="text-xs text-muted-foreground">
            {hasArtwork ? (
              <>
                {model.dataset_classes} symbols · {model.dataset_images} images in{' '}
                <span className="font-mono">games/{model.game}/symbols</span>
              </>
            ) : (
              <>
                Needs artwork for at least two symbols: one folder per symbol code, holding its images, in{' '}
                <span className="font-mono">backend/app/games/{model.game}/symbols</span>.
              </>
            )}
            {training && progress && progress.loss !== null ? ` · loss ${progress.loss.toFixed(3)}` : null}
          </p>
        ) : null}
        {model?.state === 'failed' && model.error ? (
          <p className="text-sm text-destructive">Training failed: {model.error}</p>
        ) : null}
        {status.isError ? (
          <p className="text-sm text-destructive">Could not load the model status: {status.error.message}</p>
        ) : null}
        {train.error ? <p className="text-sm text-destructive">{train.error.message}</p> : null}
      </CardContent>
    </Card>
  )
}
