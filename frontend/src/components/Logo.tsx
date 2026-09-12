import { cn } from '@/lib/utils'

/**
 * The AutoCheck logo.
 *
 * The artwork is the one designed for the project (images/image-1.png
 * and image-3.png), not a redrawing of it. What changed is the file:
 * each was ~700KB with a baked white ground and very large empty
 * margins, which meant shipping most of a megabyte to draw something
 * 32px tall, and a white rectangle wherever the theme is dark.
 *
 * Trimmed to its content, keyed to transparency and quantised to the
 * handful of colours flat vector art actually uses, the lockup is now
 * about 10KB and sits on any background. The sheet's interior goes
 * transparent with the ground, which suits outline artwork: paper in
 * light mode, an outline in dark.
 */

/** Just the document mark, for tight spaces. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <img
      src="/logo-mark.png"
      alt="AutoCheck"
      className={cn('size-8 object-contain', className)}
      // Intrinsic size, so the row doesn't reflow as it loads.
      width={278}
      height={256}
    />
  )
}

/** The mark with the name, as designed. */
export function Logo({ className }: { className?: string }) {
  return (
    <img
      src="/logo.png"
      alt="AutoCheck — automating the boring stuff"
      className={cn('h-8 w-auto object-contain', className)}
      width={564}
      height={128}
    />
  )
}
