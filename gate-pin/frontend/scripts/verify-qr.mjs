/* Structural validation of the generated QR symbol.
 *
 * A QR that renders but does not scan looks fine on screen and fails only when
 * somebody is standing at the gate. These checks assert the parts of the symbol
 * a scanner actually locks onto, so a broken library, a wrong quiet zone or a
 * transposed row/col loop fails the build instead of the visitor.
 */
import jsQR from 'jsqr'
import { buildQr, QUIET_MODULES } from '../admin/src/qr.js'

/* Rasterise the symbol exactly as the SVG renders it -- dark modules black on a
   white ground, quiet zone included -- so a real decoder can be pointed at it.
   Structural checks prove the symbol is well formed; only a decode proves it
   carries the link back. */
function rasterise(qr, scale = 6) {
  const px = qr.extent * scale
  const data = new Uint8ClampedArray(px * px * 4).fill(255)
  for (let row = 0; row < qr.count; row++) {
    for (let col = 0; col < qr.count; col++) {
      if (!qr.isDark(row, col)) continue
      const x0 = (col + QUIET_MODULES) * scale
      const y0 = (row + QUIET_MODULES) * scale
      for (let y = y0; y < y0 + scale; y++) {
        for (let x = x0; x < x0 + scale; x++) {
          const i = (y * px + x) * 4
          data[i] = data[i + 1] = data[i + 2] = 0
        }
      }
    }
  }
  return { data, px }
}

let failures = 0
const check = (name, ok, detail = '') => {
  if (ok) {
    console.log(`  ok   ${name}`)
  } else {
    failures += 1
    console.error(`  FAIL ${name}${detail ? ' — ' + detail : ''}`)
  }
}

/* A finder pattern is a 7x7 block: dark ring, light ring, 3x3 dark centre.
   All three are what a scanner locates first. */
function isFinderAt(qr, top, left) {
  for (let r = 0; r < 7; r++) {
    for (let c = 0; c < 7; c++) {
      const ring = r === 0 || r === 6 || c === 0 || c === 6
      const inner = r >= 2 && r <= 4 && c >= 2 && c <= 4
      const expected = ring || inner
      if (qr.isDark(top + r, left + c) !== expected) return false
    }
  }
  return true
}

const samples = [
  'https://gate.terica.co.za/g/4Nyl2bK_vpvBMfg9nyaaCMoV3rtV0eXG',
  'https://example.com/g/' + 'A'.repeat(32),
  'https://a.b/g/' + 'z9_-'.repeat(8),
]

for (const value of samples) {
  console.log(`\n${value.slice(0, 48)}…`)
  const qr = buildQr(value)
  check('symbol is generated', !!qr)
  if (!qr) continue

  check('module count is a valid QR size', qr.count >= 21 && (qr.count - 17) % 4 === 0, `count=${qr.count}`)
  check('quiet zone is included in the extent', qr.extent === qr.count + QUIET_MODULES * 2)
  check('quiet zone is at least 4 modules', QUIET_MODULES >= 4)

  check('top-left finder pattern', isFinderAt(qr, 0, 0))
  check('top-right finder pattern', isFinderAt(qr, 0, qr.count - 7))
  check('bottom-left finder pattern', isFinderAt(qr, qr.count - 7, 0))

  // Timing patterns: alternating modules along row 6 and column 6, between the
  // finders. A transposed row/col loop survives the finder checks but breaks here.
  let timingOk = true
  for (let i = 8; i < qr.count - 8; i++) {
    if (qr.isDark(6, i) !== (i % 2 === 0)) timingOk = false
    if (qr.isDark(i, 6) !== (i % 2 === 0)) timingOk = false
  }
  check('timing patterns alternate on row 6 and column 6', timingOk)

  // The path must place one 1x1 rect per dark module, offset by the quiet zone.
  const rects = qr.d.match(/M-?\d+ -?\d+h1v1h-1z/g) || []
  let darkCount = 0
  for (let r = 0; r < qr.count; r++) {
    for (let c = 0; c < qr.count; c++) if (qr.isDark(r, c)) darkCount++
  }
  check('path draws exactly one rect per dark module', rects.length === darkCount, `${rects.length} vs ${darkCount}`)

  const coords = rects.map((m) => m.match(/M(-?\d+) (-?\d+)/).slice(1).map(Number))
  check('every rect sits inside the quiet zone', coords.every(([x, y]) =>
    x >= QUIET_MODULES && y >= QUIET_MODULES &&
    x < qr.extent - QUIET_MODULES && y < qr.extent - QUIET_MODULES))

  // The check that actually matters: point a real decoder at the rendered
  // symbol and confirm it reads back the exact link.
  const { data, px } = rasterise(qr)
  const decoded = jsQR(data, px, px)
  check('a real decoder reads it back verbatim', decoded?.data === value,
        decoded ? `got "${decoded.data.slice(0, 40)}"` : 'decoder found no symbol')
}

console.log(failures === 0 ? '\nQR verification passed' : `\nQR verification FAILED (${failures})`)
process.exit(failures === 0 ? 0 : 1)
