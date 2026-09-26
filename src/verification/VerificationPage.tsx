import { FormEvent, useEffect, useMemo, useState } from 'react'

type VerificationState = 'loading' | 'valid' | 'revoked' | 'unknown' | 'error'
type WarrantyState = 'unregistered' | 'active' | 'expired'
type RegistrationState = 'idle' | 'submitting' | 'success' | 'error'

interface VerificationPayload {
  state: 'valid' | 'revoked' | 'unknown'
  brand_name?: string
  product_name?: string
  sku?: string
  serial?: string
  warranty_state?: WarrantyState
  warranty_started_on?: string
  warranty_expires_on?: string
  message: string
}

interface RegistrationPayload {
  registration_id: string
  replayed: boolean
  warranty_state: WarrantyState
  warranty_started_on: string
  warranty_expires_on: string
  message: string
}

function extractToken() {
  const match = window.location.pathname.match(/^\/verify\/([^/]+)\/?$/)
  return match ? decodeURIComponent(match[1]) : null
}

function apiBaseUrl() {
  return (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
}

function registrationKey(token: string) {
  const storageKey = `product-identity:registration:${token}`
  const existing = window.sessionStorage.getItem(storageKey)
  if (existing) return existing

  const generated = window.crypto.randomUUID()
  window.sessionStorage.setItem(storageKey, generated)
  return generated
}

export function VerificationPage() {
  const token = useMemo(extractToken, [])
  const [state, setState] = useState<VerificationState>('loading')
  const [payload, setPayload] = useState<VerificationPayload | null>(null)
  const [registrationState, setRegistrationState] = useState<RegistrationState>('idle')
  const [registrationError, setRegistrationError] = useState('')
  const [customerName, setCustomerName] = useState('')
  const [customerEmail, setCustomerEmail] = useState('')
  const [purchaseDate, setPurchaseDate] = useState('')

  useEffect(() => {
    if (!token) {
      setState('error')
      return
    }

    const controller = new AbortController()

    fetch(`${apiBaseUrl()}/v1/public/verify/${encodeURIComponent(token)}`, {
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
      .catch(() => {
        if (controller.signal.aborted) return
        setState('error')
      })

    return () => controller.abort()
  }, [token])

  async function submitRegistration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token || registrationState === 'submitting') return

    setRegistrationState('submitting')
    setRegistrationError('')

    try {
      const response = await fetch(
        `${apiBaseUrl()}/v1/public/register/${encodeURIComponent(token)}`,
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'Idempotency-Key': registrationKey(token),
          },
          body: JSON.stringify({
            customer_name: customerName,
            customer_email: customerEmail,
            purchase_date: purchaseDate || null,
          }),
        },
      )

      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null
        throw new Error(body?.detail ?? 'Registration could not be completed.')
      }

      const registered = (await response.json()) as RegistrationPayload
      setPayload((current) =>
        current
          ? {
              ...current,
              warranty_state: registered.warranty_state,
              warranty_started_on: registered.warranty_started_on,
              warranty_expires_on: registered.warranty_expires_on,
            }
          : current,
      )
      setRegistrationState('success')
    } catch (error: unknown) {
      setRegistrationError(
        error instanceof Error ? error.message : 'Registration could not be completed.',
      )
      setRegistrationState('error')
    }
  }

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

  const canRegister =
    state === 'valid' &&
    payload?.warranty_state === 'unregistered' &&
    registrationState !== 'success'

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
            {payload.warranty_state && (
              <div>
                <dt>Warranty</dt>
                <dd className={`warranty-state warranty-state-${payload.warranty_state}`}>
                  {payload.warranty_state === 'unregistered'
                    ? 'Not registered'
                    : payload.warranty_state === 'active'
                      ? 'Active'
                      : 'Expired'}
                </dd>
              </div>
            )}
            {payload.warranty_expires_on && (
              <div>
                <dt>Valid until</dt>
                <dd>{payload.warranty_expires_on}</dd>
              </div>
            )}
          </dl>
        )}

        {canRegister && (
          <form className="registration-form" onSubmit={submitRegistration}>
            <div className="registration-heading">
              <p className="verification-eyebrow">Warranty registration</p>
              <h2>Register this product.</h2>
              <p>
                Add your details to activate the warranty defined by the issuing brand.
              </p>
            </div>

            <label>
              <span>Name</span>
              <input
                name="customer_name"
                autoComplete="name"
                value={customerName}
                maxLength={200}
                required
                onChange={(event) => setCustomerName(event.target.value)}
              />
            </label>

            <label>
              <span>Email</span>
              <input
                name="customer_email"
                type="email"
                autoComplete="email"
                value={customerEmail}
                maxLength={320}
                required
                onChange={(event) => setCustomerEmail(event.target.value)}
              />
            </label>

            <label>
              <span>Purchase date <small>optional</small></span>
              <input
                name="purchase_date"
                type="date"
                value={purchaseDate}
                max={new Date().toISOString().slice(0, 10)}
                onChange={(event) => setPurchaseDate(event.target.value)}
              />
            </label>

            {registrationState === 'error' && (
              <p className="registration-error" role="alert">{registrationError}</p>
            )}

            <button
              className="verification-retry"
              type="submit"
              disabled={registrationState === 'submitting'}
            >
              {registrationState === 'submitting' ? 'Registering…' : 'Activate warranty'}
            </button>

            <small className="registration-privacy">
              Your registration details are visible to the issuing brand, not to people who scan this code.
            </small>
          </form>
        )}

        {registrationState === 'success' && (
          <div className="registration-success">
            <strong>Warranty activated.</strong>
            <span>
              {payload?.warranty_expires_on
                ? `Coverage is recorded through ${payload.warranty_expires_on}.`
                : 'Your registration has been recorded.'}
            </span>
          </div>
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
