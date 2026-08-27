/* Copying to the clipboard where navigator.clipboard does not exist.
 *
 * The Clipboard API is gated on a secure context. Home Assistant ingress is
 * typically plain HTTP on a LAN hostname, so `navigator.clipboard` is
 * undefined there and any `navigator.clipboard?.writeText(...)` silently
 * succeeds at doing nothing -- the button looks like it worked.
 *
 * Returns true only if something was actually copied, so the caller can tell
 * the user when it was not. */
export async function writeToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Permission denied, or the document was not focused. Fall through.
    }
  }

  // The pre-Clipboard-API route. Deprecated, still works everywhere that
  // matters, and is the only option over plain HTTP.
  try {
    const el = document.createElement('textarea')
    el.value = text
    el.setAttribute('readonly', '')
    el.style.position = 'fixed'
    el.style.top = '-9999px'
    document.body.appendChild(el)
    el.select()
    el.setSelectionRange(0, text.length) // iOS needs the explicit range
    const ok = document.execCommand('copy')
    document.body.removeChild(el)
    return ok
  } catch {
    return false
  }
}
