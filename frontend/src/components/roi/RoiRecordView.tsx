import type { ReactNode } from 'react'

import { obsScreenshotSrc } from '@/api/obs'
import { roiImageSrc } from '@/api/roi'
import type { RoiCrop, RoiRecord } from '@/types/roi'

const REGION_LABELS: Record<string, string> = {
  reels: 'Grid (reels)',
  cash_meter: 'Cash meter',
  cyclic_message: 'Cyclic message',
  cyclic_message_2: 'Cyclic message 2',
}

const regionLabel = (name: string) => REGION_LABELS[name] ?? name.replace(/_/g, ' ')

/** Fractions as configured, without the float noise: [0.0451, 0.5597, 0.9549, 0.8222]. */
const formatFractions = (roi: number[]) => `[${roi.map((value) => +value.toFixed(4)).join(', ')}]`

/**
 * An image at its natural aspect ratio, never upscaled and never cropped, whatever shape the
 * game window is. Clicking it opens the full-size file.
 */
function Figure({
  label,
  detail,
  src,
  alt,
  imageClassName,
}: {
  label: string
  detail?: ReactNode
  src: string
  alt: string
  imageClassName: string
}) {
  return (
    <figure className="min-w-0 space-y-1.5">
      <figcaption className="flex flex-wrap items-baseline gap-x-2 text-xs">
        <span className="font-medium text-foreground">{label}</span>
        {detail ? <span className="text-muted-foreground">{detail}</span> : null}
      </figcaption>
      <a
        href={src}
        target="_blank"
        rel="noreferrer"
        className="block w-fit max-w-full overflow-hidden rounded-lg border bg-muted"
      >
        <img src={src} alt={alt} className={`h-auto w-auto max-w-full ${imageClassName}`} />
      </a>
    </figure>
  )
}

function CropFigure({ crop }: { crop: RoiCrop }) {
  const label = regionLabel(crop.name)
  return (
    <Figure
      label={label}
      detail={
        <>
          {crop.width}×{crop.height} px ·{' '}
          <span className="font-mono">{formatFractions(crop.roi)}</span>
        </>
      }
      src={roiImageSrc(crop)}
      alt={`${label} region`}
      imageClassName="max-h-96"
    />
  )
}

/** The screenshot, the regions cut out of it, and the reel grid split into its tiles. */
export function RoiRecordView({ record }: { record: RoiRecord }) {
  const shotTime = new Date(record.screenshot.created_at).toLocaleTimeString()

  return (
    <div className="space-y-6">
      <Figure
        label="Full image"
        src={obsScreenshotSrc(record.screenshot)}
        alt={`Screenshot taken at ${shotTime}`}
        imageClassName="max-h-[40rem]"
      />

      <div className="flex flex-wrap items-start gap-6">
        {record.crops.map((crop) => (
          <CropFigure key={crop.name} crop={crop} />
        ))}
      </div>

      {record.tiles.length > 0 ? (
        <section className="space-y-1.5">
          <h4 className="flex flex-wrap items-baseline gap-x-2 text-xs">
            <span className="font-medium text-foreground">Tiles</span>
            <span className="text-muted-foreground">
              {record.rows} rows × {record.columns} reels
            </span>
          </h4>
          <ul
            className="grid max-w-2xl gap-2"
            style={{ gridTemplateColumns: `repeat(${record.columns}, minmax(0, 1fr))` }}
          >
            {record.tiles.map((tile) => {
              const label = `Reel ${tile.column + 1} · Row ${tile.row + 1}`
              return (
                <li key={`${tile.row}-${tile.column}`} className="min-w-0 space-y-1">
                  <a
                    href={roiImageSrc(tile)}
                    target="_blank"
                    rel="noreferrer"
                    className="block overflow-hidden rounded-md border bg-muted"
                  >
                    <img
                      src={roiImageSrc(tile)}
                      alt={`Tile: ${label}`}
                      loading="lazy"
                      className="h-auto w-full"
                    />
                  </a>
                  <p className="truncate text-[10px] text-muted-foreground" title={label}>
                    {label}
                  </p>
                </li>
              )
            })}
          </ul>
        </section>
      ) : null}
    </div>
  )
}
