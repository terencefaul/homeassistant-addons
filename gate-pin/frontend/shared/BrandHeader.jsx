import React from 'react'

/* The logo and property name shown to a visitor.
 *
 * The logo is served by the add-on itself at logoSrc. It is never hotlinked:
 * a request to an outside host from the guest page would carry the link token
 * out in the Referer header, and the CSP on the public origin forbids it.
 */
export default function BrandHeader({ logoSrc, hasLogo, propertyName, compact }) {
  if (!hasLogo && !propertyName) return null
  return (
    <header className={compact ? 'mb-5' : 'mb-8 text-center'}>
      {hasLogo && (
        <img
          src={logoSrc}
          alt={propertyName || ''}
          className={compact ? 'h-10 mb-2' : 'h-14 mb-3 mx-auto'}
          style={{ objectFit: 'contain' }}
        />
      )}
      {propertyName && (
        <p
          className={compact ? 'text-sm font-medium' : 'text-base font-medium'}
          style={{ color: 'var(--gp-muted)', letterSpacing: '0.02em' }}
        >
          {propertyName}
        </p>
      )}
    </header>
  )
}
