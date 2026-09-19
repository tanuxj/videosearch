import { useEffect, useState } from 'react'
import { humanDuration } from '../lib/format'

/**
 * Live "1m 20s" counter for a video that is still indexing.
 *
 * Ticks on its own second rather than riding the store's 3s status poll: a
 * timer that jumps three seconds at a time reads as broken, and looking like
 * it is moving is this component's entire job.
 *
 * Renders nothing when the server never recorded a start time — videos
 * indexed before the timing columns existed. That is deliberately the same
 * "show nothing" as a missing duration, because for those rows there is
 * genuinely nothing true to show.
 */
export function ProcessingTimer({ startedAt }: { startedAt?: string }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!startedAt) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [startedAt])

  if (!startedAt) return null
  const started = new Date(startedAt).getTime()
  if (Number.isNaN(started)) return null
  // Clamped: a client clock running behind the server's would otherwise
  // count backwards from a start time that is "in the future".
  return <>{humanDuration(Math.max(0, (now - started) / 1000))}</>
}
