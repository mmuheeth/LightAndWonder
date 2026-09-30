import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"
import { CircleAlert, Info, Loader2, type LucideIcon, TriangleAlert } from "lucide-react"

const noticeVariants = cva(
  "flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm shadow-xs [&>svg]:mt-0.5 [&>svg]:size-4 [&>svg]:shrink-0",
  {
    variants: {
      tone: {
        error: "border-destructive/25 bg-destructive/5 text-destructive",
        warning:
          "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200",
        info: "bg-card text-muted-foreground",
      },
    },
    defaultVariants: {
      tone: "info",
    },
  }
)

const NOTICE_ICONS: Record<NonNullable<VariantProps<typeof noticeVariants>["tone"]>, LucideIcon> = {
  error: CircleAlert,
  warning: TriangleAlert,
  info: Info,
}

/** A message about the page that is not its content: something failed, looks wrong, or needs doing first. */
function Notice({
  tone = "info",
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof noticeVariants>) {
  const Icon = NOTICE_ICONS[tone ?? "info"]
  return (
    <div
      data-slot="notice"
      role={tone === "error" ? "alert" : undefined}
      className={cn(noticeVariants({ tone }), className)}
      {...props}
    >
      <Icon aria-hidden />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

/** Where a result will appear: says that there is none yet (or that it is loading), and what to do about it. */
function EmptyState({
  icon: Icon,
  loading = false,
  title,
  className,
  children,
}: {
  icon?: LucideIcon
  loading?: boolean
  title: string
  className?: string
  children?: React.ReactNode
}) {
  const Glyph = loading ? Loader2 : Icon
  return (
    <div
      data-slot="empty-state"
      className={cn(
        "flex flex-col items-center gap-1 rounded-xl border border-dashed bg-card/60 px-6 py-10 text-center",
        className
      )}
    >
      {Glyph ? (
        <span className="mb-2 flex size-10 items-center justify-center rounded-full border bg-card text-muted-foreground shadow-card">
          <Glyph className={cn("size-5", loading && "animate-spin")} aria-hidden />
        </span>
      ) : null}
      <p className="text-sm font-medium">{title}</p>
      {children ? <p className="max-w-lg text-sm text-muted-foreground">{children}</p> : null}
    </div>
  )
}

export { Notice, EmptyState }
