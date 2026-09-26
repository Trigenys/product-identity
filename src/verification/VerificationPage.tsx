import { useEffect, useMemo, useState } from 'react'

type VerificationState = 'loading' | 'valid' | 'revoked' | 'unknown' | 'error'

interface VerificationPayload {
  state: 'valid' | 'revoked' | 'unknown'
  brand_name?: string
  product_name?: string
  sku?: string
  serial?: string
  message: string
}

function extractToken() {
  const match = window.location.pathname.match(/^\/verify\/([^/]+)\/?$/)
  return match ? decodeURIComponent(match[1]) : null
}

export function VerificationPage() {
  const token = useMemo(extractToken, [])
  const [state, setState] = useState<VerificationState>('loading')
  const [payload, setPayload] = useState<VerificationPayload | null>(null)

  useEffect(() => {
    if (!token) {
      setState('error')
      return
    }

    const controller = new AbortController()
    const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

    fetch(`${apiBase}/v1/public/verify/${encodeURIComponent(token)}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.status === 429) {
          throw new Error('rate-limited')
        }
        if (!response.ok) {
          throw new Error('verification-failed')
        }
        return response.json() as Promise<VerificationPayload>
      })
      .then((body) => {
        setPayload(body)
        setState(body.state)
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState(error instanceof Error && error.message === 'rate-limited' ? 'error' : 'error')
      })

    return () => controller.abort()
  }, [token])

  const content = {
    loading: {
      eyebrow: 'Checking identity',
      title: 'Verifying this product…',
      text: 'We are checking the digital identity attached to this code.',
    },
    valid: {
      eyebrow: 'Digital identity verified',
      title: 'This identity is active.',
      text: payload?.message ?? 'This digital product identity is active.',
    },
    revoked: {
      eyebrow: 'Identity revoked',
      title: 'This code is no longer active.',
      text:
        payload?.message ??
        'The issuing brand has revoked this digital product identity. Contact the brand before relying on it.',
    },
    unknown: {
      eyebrow: 'Code not recognized',
      title: 'We cannot verify this code.',
      text:
        payload?.message ??
        'This code does not match an identity issued by Product Identity.',
    },
    error: {
      eyebrow: 'Verification unavailable',
      title: 'We could not complete the check.',
      text: 'Try again shortly. If this persists, contact the brand that supplied the product.',
    },
  }[state]

  return (
    <main className="verification-page">
      <section className="verification-card" aria-live="polite">
        <div className={`verification-mark verification-mark-${state}`} aria-hidden="true">
          {state === 'loading' ? '···' : state === 'valid' ? '✓' : state === 'revoked' ? '!' : '?'}
        </div>

        <p className="verification-eyebrow">{content.eyebrow}</p>
        <h1>{content.title}</h1>
        <p className="verification-copy">{content.text}</p>

        {(state === 'valid' || state === 'revoked') && payload && (
          <dl className="verification-details">
            {payload.brand_name && (
              <div>
                <dt>Brand</dt>
                <dd>{payload.brand_name}</dd>
              </div>
            )}
            {payload.product_name && (
              <div>
                <dt>Product</dt>
                <dd>{payload.product_name}</dd>
              </div>
            )}
            {payload.sku && (
              <div>
                <dt>Model / SKU</dt>
                <dd>{payload.sku}</dd>
              </div>
            )}
            {payload.serial && (
              <div>
                <dt>Serial</dt>
                <dd className="verification-serial">{payload.serial}</dd>
              </div>
            )}
          </dl>
        )}

        <aside className="verification-note">
          This check confirms a digital identity issued for a product unit. A copied label can still
          require review by the issuing brand.
        </aside>

        {state === 'error' && (
          <button className="verification-retry" type="button" onClick={() => window.location.reload()}>
            Try again
          </button>
        )}

        <footer className="verification-footer">
          <span>Product Identity</span>
          <small>by Trigenys</small>
        </footer>
      </section>
    </main>
  )
}
