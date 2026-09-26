import { useEffect, useMemo, useState } from 'react'

type UnitStatus = 'active' | 'revoked'
type WarrantyState = 'active' | 'expired' | 'unregistered'
type RegistrationFilter = 'all' | 'registered' | 'unregistered'
type WarrantyFilter = 'all' | WarrantyState
type UnitStatusFilter = 'all' | UnitStatus

interface Membership {
  organization_id: string
  organization_name: string
  organization_slug: string
  role: string
}

interface MeResponse {
  id: string
  email: string | null
  memberships: Membership[]
}

interface RegistrySummary {
  total_units: number
  active_units: number
  revoked_units: number
  registered_units: number
  unregistered_units: number
  open_authenticity_signals: number
}

interface RegistryUnit {
  id: string
  serial: string
  status: UnitStatus
  product_id: string
  product_name: string
  sku: string
  created_at: string
  registered: boolean
  warranty_state: WarrantyState
  warranty_expires_on: string | null
  verification_count: number
  open_signal_count: number
}

interface RegistryResponse {
  summary: RegistrySummary
  total: number
  limit: number
  offset: number
  units: RegistryUnit[]
}

interface RegistrationDetail {
  id: string
  customer_name: string
  customer_email: string
  purchase_date: string | null
  registered_at: string
  warranty_started_on: string
  warranty_expires_on: string
  warranty_state: WarrantyState
}

interface TimelineItem {
  id: string
  kind: 'fact' | 'derived'
  source: string
  title: string
  description: string
  occurred_at: string
}

interface UnitDetail {
  id: string
  serial: string
  status: UnitStatus
  product_id: string
  product_name: string
  sku: string
  created_at: string
  registration: RegistrationDetail | null
  verification_count: number
  open_signal_count: number
  timeline: TimelineItem[]
}

function apiBaseUrl() {
  return (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
}

function accessToken() {
  return window.sessionStorage.getItem('product-identity:access-token')
}

function selectedOrganizationKey() {
  return 'product-identity:selected-organization'
}

function formatDate(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(value))
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

async function apiFetch<T>(path: string, token: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${token}`,
    },
    signal,
  })

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `Request failed with status ${response.status}`)
  }

  return response.json() as Promise<T>
}

function StatusBadge({
  tone,
  children,
}: {
  tone: 'good' | 'warn' | 'neutral' | 'danger'
  children: React.ReactNode
}) {
  return <span className={`registry-badge registry-badge-${tone}`}>{children}</span>
}

export function MerchantRegistryPage() {
  const token = useMemo(accessToken, [])
  const [me, setMe] = useState<MeResponse | null>(null)
  const [organizationId, setOrganizationId] = useState(
    () => window.sessionStorage.getItem(selectedOrganizationKey()) ?? '',
  )
  const [registry, setRegistry] = useState<RegistryResponse | null>(null)
  const [selectedUnitId, setSelectedUnitId] = useState<string | null>(null)
  const [detail, setDetail] = useState<UnitDetail | null>(null)

  const [search, setSearch] = useState('')
  const [unitStatus, setUnitStatus] = useState<UnitStatusFilter>('all')
  const [registration, setRegistration] = useState<RegistrationFilter>('all')
  const [warranty, setWarranty] = useState<WarrantyFilter>('all')

  const [sessionState, setSessionState] = useState<'loading' | 'ready' | 'missing' | 'error'>(
    token ? 'loading' : 'missing',
  )
  const [registryState, setRegistryState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [detailState, setDetailState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!token) return

    const controller = new AbortController()
    apiFetch<MeResponse>('/v1/me', token, controller.signal)
      .then((body) => {
        setMe(body)
        const validSelection = body.memberships.some(
          (membership) => membership.organization_id === organizationId,
        )
        const nextOrganization = validSelection
          ? organizationId
          : body.memberships[0]?.organization_id ?? ''
        setOrganizationId(nextOrganization)
        if (nextOrganization) {
          window.sessionStorage.setItem(selectedOrganizationKey(), nextOrganization)
        }
        setSessionState('ready')
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setError(caught instanceof Error ? caught.message : 'Merchant session could not be loaded.')
        setSessionState('error')
      })

    return () => controller.abort()
  }, [token])

  useEffect(() => {
    if (!token || !organizationId || sessionState !== 'ready') return

    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setRegistryState('loading')

      const query = new URLSearchParams()
      if (search.trim()) query.set('search', search.trim())
      if (unitStatus !== 'all') query.set('unit_status', unitStatus)
      if (registration !== 'all') query.set('registration', registration)
      if (warranty !== 'all') query.set('warranty', warranty)
      query.set('limit', '100')

      apiFetch<RegistryResponse>(
        `/v1/organizations/${organizationId}/registry/units?${query.toString()}`,
        token,
        controller.signal,
      )
        .then((body) => {
          setRegistry(body)
          setRegistryState('ready')
          setError('')
          if (selectedUnitId && !body.units.some((unit) => unit.id === selectedUnitId)) {
            setSelectedUnitId(null)
            setDetail(null)
            setDetailState('idle')
          }
        })
        .catch((caught: unknown) => {
          if (controller.signal.aborted) return
          setError(caught instanceof Error ? caught.message : 'Registry could not be loaded.')
          setRegistryState('error')
        })
    }, 180)

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [token, organizationId, sessionState, search, unitStatus, registration, warranty])

  useEffect(() => {
    if (!token || !organizationId || !selectedUnitId) {
      setDetail(null)
      setDetailState('idle')
      return
    }

    const controller = new AbortController()
    setDetailState('loading')

    apiFetch<UnitDetail>(
      `/v1/organizations/${organizationId}/registry/units/${selectedUnitId}`,
      token,
      controller.signal,
    )
      .then((body) => {
        setDetail(body)
        setDetailState('ready')
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setError(caught instanceof Error ? caught.message : 'Unit detail could not be loaded.')
        setDetailState('error')
      })

    return () => controller.abort()
  }, [token, organizationId, selectedUnitId])

  function selectOrganization(next: string) {
    setOrganizationId(next)
    window.sessionStorage.setItem(selectedOrganizationKey(), next)
    setSelectedUnitId(null)
    setDetail(null)
  }

  if (sessionState === 'missing') {
    return (
      <main className="registry-auth-shell">
        <section className="registry-auth-card">
          <p className="registry-kicker">Product Identity · Merchant</p>
          <h1>Merchant session required.</h1>
          <p>
            The registry uses the OIDC/JWT contract already implemented by Product Identity. No
            temporary password form or token-in-URL fallback is enabled.
          </p>
          <small>
            The authentication provider and callback UX are intentionally handled by the dedicated
            auth/integration milestone.
          </small>
        </section>
      </main>
    )
  }

  if (sessionState === 'loading') {
    return (
      <main className="registry-auth-shell">
        <section className="registry-auth-card">
          <p className="registry-kicker">Product Identity · Merchant</p>
          <h1>Loading your workspace…</h1>
        </section>
      </main>
    )
  }

  if (sessionState === 'error') {
    return (
      <main className="registry-auth-shell">
        <section className="registry-auth-card">
          <p className="registry-kicker">Session error</p>
          <h1>We could not open the merchant workspace.</h1>
          <p>{error}</p>
        </section>
      </main>
    )
  }

  if (!me?.memberships.length) {
    return (
      <main className="registry-auth-shell">
        <section className="registry-auth-card">
          <p className="registry-kicker">Product Identity · Merchant</p>
          <h1>No organization access.</h1>
          <p>Your authenticated account does not currently belong to a Product Identity organization.</p>
        </section>
      </main>
    )
  }

  const summary = registry?.summary
  const activeMembership = me.memberships.find(
    (membership) => membership.organization_id === organizationId,
  )

  return (
    <main className="registry-page">
      <header className="registry-topbar">
        <div>
          <p className="registry-kicker">Product Identity</p>
          <strong>Unit Registry</strong>
        </div>

        <div className="registry-topbar-actions">
          <label className="registry-org-switcher">
            <span>Organization</span>
            <select value={organizationId} onChange={(event) => selectOrganization(event.target.value)}>
              {me.memberships.map((membership) => (
                <option key={membership.organization_id} value={membership.organization_id}>
                  {membership.organization_name}
                </option>
              ))}
            </select>
          </label>
          <div className="registry-user">
            <span>{me.email ?? 'Merchant user'}</span>
            <small>{activeMembership?.role ?? 'member'}</small>
          </div>
        </div>
      </header>

      <section className="registry-heading">
        <div>
          <p className="registry-kicker">Operations</p>
          <h1>Know every unit.</h1>
          <p>
            Search issued products, see registration and warranty state, and review scan anomalies
            without mixing source facts with derived signals.
          </p>
        </div>
        <div className="registry-live-pill">
          <span aria-hidden="true" />
          Tenant-scoped registry
        </div>
      </section>

      <section className="registry-summary" aria-label="Registry summary">
        <article>
          <span>Total units</span>
          <strong>{summary?.total_units ?? '—'}</strong>
        </article>
        <article>
          <span>Registered</span>
          <strong>{summary?.registered_units ?? '—'}</strong>
        </article>
        <article>
          <span>Revoked</span>
          <strong>{summary?.revoked_units ?? '—'}</strong>
        </article>
        <article>
          <span>Open signals</span>
          <strong>{summary?.open_authenticity_signals ?? '—'}</strong>
        </article>
      </section>

      <section className="registry-workspace">
        <div className="registry-list-pane">
          <div className="registry-toolbar">
            <label className="registry-search">
              <span className="sr-only">Search registry</span>
              <input
                type="search"
                placeholder="Search serial, product or SKU"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>

            <div className="registry-filters">
              <select value={unitStatus} onChange={(event) => setUnitStatus(event.target.value as UnitStatusFilter)}>
                <option value="all">All unit states</option>
                <option value="active">Active units</option>
                <option value="revoked">Revoked units</option>
              </select>
              <select value={registration} onChange={(event) => setRegistration(event.target.value as RegistrationFilter)}>
                <option value="all">All registrations</option>
                <option value="registered">Registered</option>
                <option value="unregistered">Unregistered</option>
              </select>
              <select value={warranty} onChange={(event) => setWarranty(event.target.value as WarrantyFilter)}>
                <option value="all">All warranty states</option>
                <option value="active">Active warranty</option>
                <option value="expired">Expired warranty</option>
                <option value="unregistered">Not registered</option>
              </select>
            </div>
          </div>

          {registryState === 'loading' && !registry && (
            <div className="registry-state">
              <strong>Loading units…</strong>
              <span>Querying this organization only.</span>
            </div>
          )}

          {registryState === 'error' && (
            <div className="registry-state registry-state-error">
              <strong>Registry unavailable.</strong>
              <span>{error}</span>
            </div>
          )}

          {registryState !== 'error' && registry?.units.length === 0 && (
            <div className="registry-state">
              <strong>No units match these filters.</strong>
              <span>Change the search or filter set. No destructive action was performed.</span>
            </div>
          )}

          {!!registry?.units.length && (
            <>
              <div className="registry-result-meta">
                <span>{registry.total} matching unit{registry.total === 1 ? '' : 's'}</span>
                {registryState === 'loading' && <small>Refreshing…</small>}
              </div>

              <div className="registry-unit-list">
                {registry.units.map((unit) => (
                  <button
                    type="button"
                    key={unit.id}
                    className={`registry-unit-row ${selectedUnitId === unit.id ? 'is-selected' : ''}`}
                    onClick={() => setSelectedUnitId(unit.id)}
                  >
                    <div className="registry-unit-main">
                      <strong>{unit.product_name}</strong>
                      <span>{unit.serial}</span>
                      <small>{unit.sku}</small>
                    </div>

                    <div className="registry-unit-states">
                      <StatusBadge tone={unit.status === 'active' ? 'good' : 'danger'}>
                        {unit.status}
                      </StatusBadge>
                      <StatusBadge
                        tone={
                          unit.warranty_state === 'active'
                            ? 'good'
                            : unit.warranty_state === 'expired'
                              ? 'warn'
                              : 'neutral'
                        }
                      >
                        {unit.warranty_state}
                      </StatusBadge>
                      {unit.open_signal_count > 0 && (
                        <StatusBadge tone="warn">
                          {unit.open_signal_count} signal{unit.open_signal_count === 1 ? '' : 's'}
                        </StatusBadge>
                      )}
                    </div>

                    <div className="registry-unit-metrics">
                      <span>{unit.verification_count} scans</span>
                      <span>{unit.registered ? 'Registered' : 'Not registered'}</span>
                    </div>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <aside className={`registry-detail-pane ${selectedUnitId ? 'is-open' : ''}`}>
          {!selectedUnitId && (
            <div className="registry-detail-empty">
              <span>01</span>
              <strong>Select a unit</strong>
              <p>Its identity facts, registration and derived authenticity signals will appear here.</p>
            </div>
          )}

          {selectedUnitId && detailState === 'loading' && (
            <div className="registry-state">
              <strong>Loading unit history…</strong>
            </div>
          )}

          {selectedUnitId && detailState === 'error' && (
            <div className="registry-state registry-state-error">
              <strong>Unit detail unavailable.</strong>
              <span>{error}</span>
            </div>
          )}

          {detailState === 'ready' && detail && (
            <div className="registry-detail-content">
              <div className="registry-detail-head">
                <button
                  type="button"
                  className="registry-detail-close"
                  onClick={() => setSelectedUnitId(null)}
                  aria-label="Close unit detail"
                >
                  ×
                </button>
                <p className="registry-kicker">Physical unit</p>
                <h2>{detail.product_name}</h2>
                <code>{detail.serial}</code>
                <div className="registry-detail-badges">
                  <StatusBadge tone={detail.status === 'active' ? 'good' : 'danger'}>
                    {detail.status}
                  </StatusBadge>
                  {detail.open_signal_count > 0 && (
                    <StatusBadge tone="warn">{detail.open_signal_count} open signal</StatusBadge>
                  )}
                </div>
              </div>

              <dl className="registry-detail-grid">
                <div>
                  <dt>SKU</dt>
                  <dd>{detail.sku}</dd>
                </div>
                <div>
                  <dt>Issued</dt>
                  <dd>{formatDate(detail.created_at)}</dd>
                </div>
                <div>
                  <dt>Verifications</dt>
                  <dd>{detail.verification_count}</dd>
                </div>
                <div>
                  <dt>Warranty</dt>
                  <dd>{detail.registration?.warranty_state ?? 'unregistered'}</dd>
                </div>
              </dl>

              <section className="registry-detail-section">
                <div className="registry-section-title">
                  <h3>Registration</h3>
                  <span>Source fact</span>
                </div>

                {detail.registration ? (
                  <dl className="registry-registration">
                    <div>
                      <dt>Customer</dt>
                      <dd>{detail.registration.customer_name}</dd>
                    </div>
                    <div>
                      <dt>Email</dt>
                      <dd>{detail.registration.customer_email}</dd>
                    </div>
                    <div>
                      <dt>Purchase date</dt>
                      <dd>{formatDate(detail.registration.purchase_date)}</dd>
                    </div>
                    <div>
                      <dt>Warranty until</dt>
                      <dd>{formatDate(detail.registration.warranty_expires_on)}</dd>
                    </div>
                  </dl>
                ) : (
                  <p className="registry-muted">This unit has not been registered by a customer.</p>
                )}
              </section>

              <section className="registry-detail-section">
                <div className="registry-section-title">
                  <h3>Timeline</h3>
                  <span>{detail.timeline.length} entries</span>
                </div>

                <div className="registry-timeline">
                  {detail.timeline.map((item) => (
                    <article key={item.id} className={`registry-timeline-item registry-timeline-${item.kind}`}>
                      <div className="registry-timeline-marker" aria-hidden="true" />
                      <div>
                        <div className="registry-timeline-meta">
                          <StatusBadge tone={item.kind === 'fact' ? 'neutral' : 'warn'}>
                            {item.kind === 'fact' ? 'Fact' : 'Derived signal'}
                          </StatusBadge>
                          <span>{formatDateTime(item.occurred_at)}</span>
                        </div>
                        <strong>{item.title}</strong>
                        <p>{item.description}</p>
                        <small>{item.source}</small>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            </div>
          )}
        </aside>
      </section>
    </main>
  )
}
