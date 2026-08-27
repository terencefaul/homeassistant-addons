import React, { useMemo } from 'react'
import { buildQr } from './qr.js'

export default function QrCode({ value, size = 208, alt = 'QR code' }) {
  const model = useMemo(() => {
    try {
      return buildQr(value)
    } catch {
      // Only reachable if the value exceeds the largest QR version. The link is
      // copyable regardless, so degrade rather than break the mint screen.
      return null
    }
  }, [value])

  if (!model) return null

  return (
    <svg
      role="img"
      aria-label={alt}
      width={size}
      height={size}
      viewBox={`0 0 ${model.extent} ${model.extent}`}
      /* Always dark-on-light, never themed. Inverted QR codes are rejected by a
         large share of scanners, and this panel is otherwise dark. */
      style={{ background: '#ffffff', borderRadius: 12, shapeRendering: 'crispEdges' }}
    >
      <rect width={model.extent} height={model.extent} fill="#ffffff" />
      <path d={model.d} fill="#000000" />
    </svg>
  )
}
