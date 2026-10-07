// Budget: credits committed this London month against the cap, per character, the projection, the cap
// editor and the kill switch (two taps, so it is never hit by accident).
import { OctagonPause, Play } from 'lucide-react';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Section, Skeleton, Spinner } from '../components/ui';
import { formatCredits } from '../lib/format';
import { KILL_SWITCH_COPY, spendState } from '../lib/rules';
import { useStudio } from '../lib/store';

const SERIES: Record<string, string> = {
  franz: 'var(--series-franz)', reginald: 'var(--series-reginald)', lenny: 'var(--series-lenny)', biscuit: 'var(--series-biscuit)',
};

/** The month's credits and the kill switch. `embedded`: inside More, under its Budget switch, which names it (no page frame, no title of its own). */
export function Budget({ account, embedded = false }: { account?: ReactNode; embedded?: boolean }) {
  const { data, backend, run, busy } = useStudio();
  const b = data?.budget ?? null;
  const [cap, setCap] = useState('');
  const [arming, setArming] = useState(false);
  useEffect(() => {
    if (b) setCap(String(b.cap));
  }, [b?.cap]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!arming) return;
    const t = window.setTimeout(() => setArming(false), 5000);
    return () => window.clearTimeout(t);
  }, [arming]);

  if (!data) {
    return (
      <div className={embedded ? 'stack' : 'page stack'} aria-busy="true">
        <Skeleton h={220} />
      </div>
    );
  }
  if (!b) {
    return (
      <div className={embedded ? undefined : 'page'}>
        <div className="panel empty">
          <b>No budget row</b>
          <span className="small muted">The settings row of migration 0001 is missing, or this account cannot read it.</span>
        </div>
      </div>
    );
  }

  const s = spendState(b);
  const capValue = Number(cap);
  const capValid = cap.trim() !== '' && Number.isInteger(capValue) && capValue >= 0;
  const saveCap = (e: FormEvent) => {
    e.preventDefault();
    if (!capValid || capValue === b.cap) return;
    void run('cap', () => backend.setBudget(capValue, null), `Monthly cap set to ${formatCredits(capValue)}`);
  };
  const toggleKill = () => {
    if (!arming) {
      setArming(true);
      return;
    }
    setArming(false);
    const next = !b.kill_switch;
    void run('kill', () => backend.setBudget(null, next), next ? KILL_SWITCH_COPY.toastOn : KILL_SWITCH_COPY.toastOff);
  };
  const total = b.by_character.reduce((t, c) => t + c.committed, 0);

  return (
    <div className={embedded ? 'stack' : 'page stack'}>
      <div>
        {!embedded && <h1 className="h1">Budget</h1>}
        <p className="small muted num" style={{ margin: '6px 0 0' }}>
          {b.month} · day {b.day_of_month} of {b.days_in_month} · Higgsfield credits, London month
        </p>
      </div>

      <Section id="committed" title="Committed this month" aside={s.pct == null ? undefined : `${Math.round(s.pct)}% of cap`}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 48, fontWeight: 600, fontStretch: '72%', lineHeight: 1 }}>{formatCredits(b.committed)}</span>
          <span className="muted num">of {formatCredits(b.cap)}</span>
        </div>
        <div
          className={`meter ${s.tone === 'ok' ? '' : s.tone}`}
          role="meter"
          aria-valuemin={0}
          aria-valuemax={b.cap}
          aria-valuenow={b.committed}
          aria-label={`Committed ${b.committed} of ${b.cap} credits`}
          style={{ height: 18 }}
        >
          <span className="fill" style={{ width: `${Math.min(100, s.pct ?? 0)}%` }} />
          {b.cap > 0 && <span className="tick" style={{ left: '80%' }} title="80% warning line" />}
          {s.projectedPct != null && <span className="proj" style={{ left: `${Math.min(99.5, s.projectedPct)}%` }} />}
        </div>
        <div className="meter-scale">
          <span>0</span>
          <span>80% · {formatCredits(Math.round(b.cap * 0.8))}</span>
          <span>{formatCredits(b.cap)}</span>
        </div>
        <div className="kv" style={{ marginTop: 6 }}>
          <div>
            <span className="label">Settled</span>
            <span className="v">{formatCredits(b.settled)}</span>
          </div>
          <div>
            <span className="label">Reserved</span>
            <span className="v">{formatCredits(b.reserved)}</span>
          </div>
          <div>
            <span className="label">Left</span>
            <span className="v">{formatCredits(s.remaining)}</span>
          </div>
        </div>
        <p className="small" style={{ margin: 0 }}>
          <span className="proj-key" data-tone={s.projectedTone}>
            <i aria-hidden="true" /> At this pace the month ends at {formatCredits(s.projected)}
            {s.projectedTone === 'over' ? ': past the cap, the daily run will stop early.' : s.projectedTone === 'warn' ? ': above the 80% line.' : '.'}
          </span>
        </p>
      </Section>

      <Section id="by-character" title="By character">
        {total > 0 ? (
          <>
            <div className="stackbar" role="img" aria-label={b.by_character.map((c) => `${c.name} ${c.committed} credits`).join(', ')}>
              {b.by_character
                .filter((c) => c.committed > 0)
                .map((c) => (
                  <span key={c.slug} style={{ flex: c.committed, background: SERIES[c.slug] ?? 'var(--ink-2)' }} title={`${c.name}: ${formatCredits(c.committed)}`} />
                ))}
            </div>
            <div className="legend">
              {b.by_character.map((c) => (
                <span key={c.slug} className="num">
                  <i style={{ background: SERIES[c.slug] ?? 'var(--ink-2)' }} />
                  {c.name} {formatCredits(c.committed)}
                  {c.reserved ? ` (${formatCredits(c.reserved)} reserved)` : ''}
                </span>
              ))}
            </div>
          </>
        ) : (
          <span className="small muted">Nothing spent yet this month.</span>
        )}
      </Section>

      <Section id="cap" title="Monthly cap">
        <form onSubmit={saveCap} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <div className="field" style={{ flex: '1 1 180px' }}>
            <label className="sr-only" htmlFor="cap-input">Monthly cap in credits</label>
            <input
              id="cap-input"
              className="input num"
              inputMode="numeric"
              pattern="[0-9]*"
              value={cap}
              onChange={(e) => setCap(e.target.value.replace(/[^0-9]/g, ''))}
              aria-invalid={!capValid || undefined}
              aria-describedby="cap-hint"
            />
            <span className="hint" id="cap-hint">
              Credits per London month. The daily run stops at the first clip that would pass it. Default 6,000.
            </span>
          </div>
          <button type="submit" className="btn line" disabled={!capValid || capValue === b.cap || busy.has('cap')} aria-busy={busy.has('cap')}>
            {busy.has('cap') && <Spinner />} Save cap
          </button>
        </form>
      </Section>

      <Section id="kill" title="Kill switch">
        <div className={`panel kill${b.kill_switch ? ' on' : ''}`}>
          <span>
            {b.kill_switch ? KILL_SWITCH_COPY.on : KILL_SWITCH_COPY.off}
          </span>
          <button
            type="button"
            className={`btn ${b.kill_switch ? 'line' : arming ? 'danger solid' : 'danger'} block`}
            onClick={toggleKill}
            disabled={busy.has('kill')}
            aria-busy={busy.has('kill')}
            aria-pressed={b.kill_switch}
          >
            {busy.has('kill') ? <Spinner /> : b.kill_switch ? <Play aria-hidden="true" /> : <OctagonPause aria-hidden="true" />}
            {b.kill_switch
              ? arming ? KILL_SWITCH_COPY.resumeArming : KILL_SWITCH_COPY.resumeButton
              : arming ? KILL_SWITCH_COPY.stopArming : KILL_SWITCH_COPY.stopButton}
          </button>
        </div>
      </Section>

      {account}
    </div>
  );
}
