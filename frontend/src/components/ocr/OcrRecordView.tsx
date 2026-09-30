import { Loader2 } from 'lucide-react'

import { roiImageSrc } from '@/api/roi'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Notice } from '@/components/ui/notice'
import { cn } from '@/lib/utils'
import type { AmountRead, CashMeterReading, CreditMeterReading, OcrCrop, OcrRecord, TextRead } from '@/types/ocr'

/** A reading the recognizer was less sure of than this (percent) is shown as doubtful. */
const DOUBTFUL_BELOW = 80

type MeterKind = 'credits' | 'cash'

interface Meter {
  crop: OcrCrop
  /** Null until the crop has been read, or when its labels did not say which meter it is. */
  kind: MeterKind | null
  reading: CreditMeterReading | CashMeterReading | null
}

const MESSAGES = [
  { name: 'cyclic_message', title: 'Cyclic message 1' },
  { name: 'cyclic_message_2', title: 'Cyclic message 2' },
] as const

const METER_TITLES = { credits: 'Credit meter', cash: 'Cash meter' }

const formatValue = (value: number, kind: MeterKind) => (kind === 'cash' ? value.toFixed(2) : String(value))

const balanceOf = (reading: CreditMeterReading | CashMeterReading): AmountRead =>
  'credits' in reading ? reading.credits : reading.cash

/**
 * The meters that were captured, credit before cash. A meter captured without knowing which it was (`meter`)
 * is whichever its reading turned out to be.
 */
function metersOf(record: OcrRecord): Meter[] {
  const { credit_meter, cash_meter } = record.readings ?? {}
  return record.crops.flatMap((crop): Meter[] => {
    if (crop.name === 'credit_meter') return [{ crop, kind: 'credits', reading: credit_meter ?? null }]
    if (crop.name === 'cash_meter') return [{ crop, kind: 'cash', reading: cash_meter ?? null }]
    if (crop.name !== 'meter') return []
    if (credit_meter) return [{ crop, kind: 'credits', reading: credit_meter }]
    if (cash_meter) return [{ crop, kind: 'cash', reading: cash_meter }]
    return [{ crop, kind: null, reading: null }]
  })
}

function Confidence({ value }: { value: number | null }) {
  if (value === null) return null
  const doubtful = value < DOUBTFUL_BELOW
  return (
    <span
      className={cn('font-mono', doubtful && 'font-medium text-amber-700 dark:text-amber-400')}
      title={doubtful ? `The recognizer was only ${value}% sure` : 'How sure the recognizer was'}
    >
      {value.toFixed(0)}%
    </span>
  )
}

/** The cut-out image at its natural size (never stretched beyond the card); clicking opens the file. */
function CropImage({ crop, title, scale = 1 }: { crop: OcrCrop; title: string; scale?: number }) {
  return (
    <a
      href={roiImageSrc(crop)}
      target="_blank"
      rel="noreferrer"
      className="block w-fit max-w-full overflow-hidden rounded-lg border bg-muted"
    >
      <img
        src={roiImageSrc(crop)}
        alt={`${title} as cut from the screenshot`}
        width={crop.width * scale}
        height={crop.height * scale}
        className="block h-auto max-w-full [image-rendering:pixelated]"
      />
    </a>
  )
}

function Reading() {
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" />
      Reading…
    </p>
  )
}

/** Things worth the person's attention: why only one meter was captured, or what looked wrong in a reading. */
function Warnings({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <Notice tone="warning">
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </Notice>
  )
}

/** One amount of the meter: its label as the game prints it, the value without the currency, and what was read. */
function Amount({
  label,
  amount,
  kind,
  emptyLabel,
}: {
  label: string
  amount: AmountRead
  kind: MeterKind
  emptyLabel: string
}) {
  return (
    <div className="min-w-0 space-y-0.5 rounded-lg border bg-muted/60 px-3 py-2">
      <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">{label}</p>
      {amount.text === null ? (
        <p className="py-1 text-sm text-muted-foreground italic">{emptyLabel}</p>
      ) : (
        <>
          <p className="font-mono text-xl">{amount.value === null ? '?' : formatValue(amount.value, kind)}</p>
          <p className="truncate text-xs text-muted-foreground">
            read as <span className="font-mono text-foreground">{amount.text}</span> · <Confidence value={amount.confidence} />
          </p>
        </>
      )}
    </div>
  )
}

function MeterCard({ meter, pending }: { meter: Meter; pending: boolean }) {
  const { crop, kind, reading } = meter
  const title = kind ? METER_TITLES[kind] : 'Meter'
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          {crop.width}×{crop.height} px
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <CropImage crop={crop} title={title} />
        {reading && kind ? (
          <>
            <div className="grid max-w-2xl grid-cols-3 gap-3">
              <Amount
                label={kind === 'credits' ? 'Credits' : 'Cash'}
                amount={balanceOf(reading)}
                kind={kind}
                emptyLabel="not found"
              />
              <Amount label="Win" amount={reading.win} kind={kind} emptyLabel="no win" />
              <Amount label="Bet" amount={reading.bet} kind={kind} emptyLabel="not found" />
            </div>
            <Warnings items={reading.issues} />
          </>
        ) : pending ? (
          <Reading />
        ) : null}
      </CardContent>
    </Card>
  )
}

function MessageCard({ title, crop, read, pending }: { title: string; crop: OcrCrop; read: TextRead | null; pending: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          {crop.width}×{crop.height} px
        </CardDescription>
        {read ? (
          <CardAction>
            <Confidence value={read.confidence} />
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3">
        <CropImage crop={crop} title={title} scale={2} />
        {read ? (
          read.text ? (
            <p className="font-mono text-base">{read.text}</p>
          ) : (
            <p className="text-sm text-muted-foreground italic" title="Nothing was on show in this message area">
              (blank)
            </p>
          )
        ) : pending ? (
          <Reading />
        ) : null}
      </CardContent>
    </Card>
  )
}

/**
 * The credit meter, cash meter and cyclic messages of one capture, each as the image that was cut out and, once
 * the OCR has run, the values read from it. `reading` is true while it is running.
 */
export function OcrRecordView({ record, reading }: { record: OcrRecord; reading: boolean }) {
  const { readings } = record
  const pending = reading && readings === null
  return (
    <div className="space-y-4">
      <Warnings items={[...record.notes, ...(readings?.issues ?? [])]} />
      {metersOf(record).map((meter) => (
        <MeterCard key={meter.crop.name} meter={meter} pending={pending} />
      ))}
      <div className="grid gap-4 md:grid-cols-2">
        {MESSAGES.map(({ name, title }) => {
          const crop = record.crops.find((candidate) => candidate.name === name)
          return crop ? (
            <MessageCard key={name} title={title} crop={crop} read={readings?.[name] ?? null} pending={pending} />
          ) : null
        })}
      </div>
    </div>
  )
}
