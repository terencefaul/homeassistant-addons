import qrcode from 'qrcode-generator'

/* The spec's minimum quiet zone. Scanners fail without it far more often than
   people expect, and the failure looks like "the camera just won't pick it up". */
export const QUIET_MODULES = 4

/* Build an SVG path for a QR symbol.
 *
 * Kept separate from the React component so scripts/verify-qr.mjs exercises the
 * real code rather than a reimplementation of it. A QR that renders but does
 * not scan is exactly the kind of fault nobody notices until somebody is
 * standing at the gate holding up a phone. */
export function buildQr(value) {
  if (!value) return null
  // Type 0 = smallest version that fits. 'M' recovers ~15% of the symbol,
  // ample for a screen or a printed sign indoors.
  const qr = qrcode(0, 'M')
  qr.addData(value)
  qr.make()
  const count = qr.getModuleCount()
  let d = ''
  for (let row = 0; row < count; row++) {
    for (let col = 0; col < count; col++) {
      if (qr.isDark(row, col)) {
        d += `M${col + QUIET_MODULES} ${row + QUIET_MODULES}h1v1h-1z`
      }
    }
  }
  return { d, count, extent: count + QUIET_MODULES * 2, isDark: (r, c) => qr.isDark(r, c) }
}
