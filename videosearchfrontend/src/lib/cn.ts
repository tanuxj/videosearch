import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Merge class names, letting later Tailwind utilities beat earlier ones.
 *
 * `clsx` flattens conditionals; `twMerge` then resolves genuine conflicts, so
 * `cn('px-4', 'px-6')` yields `px-6` instead of shipping both and relying on
 * source order. Standard helper for every component under `components/ui`.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
