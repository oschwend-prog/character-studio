// Viral Picks: new picks best-first with their six sub-scores, Approve / Skip (with reason) and a
// character override; a paste box for the owner's own links; the decided picks with what they became.
import { ExternalLink, Link2, Plus } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Flap, Livery, Section, Skeleton, Spinner, characterName } from '../components/ui';
import { formatViews, outlierBadge, platformName } from '../lib/format';

const formatOutlier = (x: number) => outlierBadge(x).label;
import { href } from '../lib/hooks';
import { canonicalVideoUrl, sortPicks } from '../lib/rules';
import { useStudio } from '../lib/store';
import type { Pick } from '../lib/types';

const CHARACTERS = ['biscuit', 'reginald'] as const;
const SCORES: { key: keyof Pick; name: string; weight: string }[] = [
  { key: 'virality', name: 'Virality', weight: '25%' },
  { key: 'fit', name: 'Fit', weight: '20%' },
  { key: 'feasibility', name: 'Feasible', weight: '20%' },
  { key: 'freshness', name: 'Fresh', weight: '15%' },
  { key: 'reach', name: 'Reach', weight: '10%' },
  { key: 'saturation', name: 'Unsaturated', weight: '10%' },
];
const SKIP_REASONS = ['Not our brand', 'Too hard to make now', 'Seen it everywhere', 'Wrong character'];

export function Picks() {
  const { data } = useStudio();
  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={120} />
        <Skeleton h={300} />
      </div>
    );
  }
  const picks = sortPicks(data.picks);
  return (
    <div className="page stack">
      <div>
        <h1 className="h1">Viral Picks</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          Best first. The standing rule already approved anything 80+ with feasibility 7+; these wait for a call.
        </p>
      </div>
      <PasteBox />
      <Section id="new-picks" title={`New · ${picks.length}`} aside="sorted by total score">
        {picks.length === 0 ? (
          <div className="panel empty">
            <b>No picks waiting</b>
            <span className="muted small">The daily scan files new ones on Tue, Thu, Sat and Sun. Paste a link above to add your own.</span>
          </div>
        ) : (
          <div className="picks-grid stack" style={{ gap: 12 }}>
            {picks.map((p) => (
              <PickCard key={p.id} pick={p} />
            ))}
          </div>
        )}
      </Section>
      <History />
    </div>
  );
}

function PasteBox() {
  const { backend, run, busy, toast } = useStudio();
  const [url, setUrl] = useState('');
  const [slug, setSlug] = useState<string>('biscuit');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    let canonical: string;
    try {
      canonical = canonicalVideoUrl(url).url;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return;
    }
    setError(null);
    const ok = await run('paste', async () => {
      const r = await backend.addOwnerLink(canonical, slug, note.trim() || null);
      toast(
        r.duplicate
          ? 'Already in your picks: approved for you if it was waiting or skipped'
          : `Added for ${characterName(slug)}: the next daily run makes it`,
      );
    });
    if (ok) {
      setUrl('');
      setNote('');
    }
  };

  return (
    <form className="panel paste" onSubmit={submit} aria-labelledby="paste-title">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Link2 size={16} aria-hidden="true" />
        <b id="paste-title" style={{ fontSize: 14 }}>Add your own link</b>
      </div>
      <div className="paste-row">
        <label className="sr-only" htmlFor="paste-url">TikTok, Instagram Reel or YouTube Shorts link</label>
        <input
          id="paste-url"
          className="input"
          type="url"
          inputMode="url"
          autoComplete="off"
          placeholder="https://www.tiktok.com/@creator/video/…"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setError(null);
          }}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'paste-err' : undefined}
          required
        />
        {!url.trim() && (
          <button type="submit" className="btn line" disabled aria-label="Add link">
            <Plus aria-hidden="true" /> Add
          </button>
        )}
      </div>
      {url.trim() ? (
        <>
          <div className="paste-row">
            <CharacterSeg value={slug} onChange={setSlug} label="Character for this link" />
          </div>
          <div className="paste-row">
            <label className="sr-only" htmlFor="paste-note">Note for the daily run (optional)</label>
            <input id="paste-note" className="input" placeholder="Note (optional): what to keep, what to change" value={note} onChange={(e) => setNote(e.target.value)} />
            <button type="submit" className="btn primary" disabled={busy.has('paste')} aria-busy={busy.has('paste')}>
              {busy.has('paste') ? <Spinner /> : <Plus aria-hidden="true" />} Add
            </button>
          </div>
        </>
      ) : (
        <span className="hint">TikTok, Instagram Reel or YouTube Shorts. Approved on the spot, never downloaded.</span>
      )}
      {error && (
        <span id="paste-err" className="error-text" role="alert">
          {error}
        </span>
      )}
    </form>
  );
}

function CharacterSeg({ value, onChange, label }: { value: string | null; onChange(v: string): void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {CHARACTERS.map((c) => (
        <button key={c} type="button" className={c} aria-pressed={value === c} onClick={() => onChange(c)}>
          {characterName(c)}
        </button>
      ))}
    </div>
  );
}

function PickCard({ pick }: { pick: Pick }) {
  const { backend, run, busy } = useStudio();
  const [slug, setSlug] = useState<string | null>(pick.character_slug);
  const [skipping, setSkipping] = useState(false);
  const [reason, setReason] = useState('');
  const key = `pick-${pick.id}`;
  const working = busy.has(key);
  const needs = Array.isArray(pick.needs) ? pick.needs.join(', ') : pick.needs;
  const titleId = `pick-${pick.id}-t`;

  const approve = () =>
    run(key, () => backend.decidePick(pick.id, 'approve', null, slug !== pick.character_slug ? slug : null), `Approved for ${characterName(slug)}: it joins the production queue`);
  const skip = (e: FormEvent) => {
    e.preventDefault();
    void run(key, () => backend.decidePick(pick.id, 'skip', reason.trim() || null, null), 'Skipped');
  };

  return (
    <article className="panel pick" aria-labelledby={titleId}>
      <div className="pick-top">
        <div className="pick-total">
          <Flap text={pick.total_score == null ? '--' : String(Math.round(pick.total_score))} label={`Total score ${pick.total_score ?? 'not scored'} of 100`} />
          <span className="label">score</span>
        </div>
        <div className="pick-head">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Livery slug={slug} />
            <span className="small muted">
              {slug ? characterName(slug) : pick.intended_character ? `For ${pick.intended_character} (not built yet)` : 'No character yet'}
              {pick.proposed_mode ? ` · ${pick.proposed_mode}` : ''}
            </span>
          </div>
          <h3 className="pick-hook" id={titleId} style={{ margin: 0 }}>
            {pick.hook ? `“${pick.hook}”` : pick.creator_handle ?? pick.url}
          </h3>
          <div className="pick-meta">
            <span>{platformName(pick.platform)}</span>
            {pick.creator_handle && <span>{pick.creator_handle}</span>}
            <span className="num">{formatViews(pick.views)} views</span>
            {pick.outlier_x != null && (
              <span className="tag num" title="Views against the creator's own median">
                {formatOutlier(pick.outlier_x)} their median
              </span>
            )}
          </div>
        </div>
      </div>

      {pick.concept && <p className="pick-concept" style={{ margin: 0 }}>{pick.concept}</p>}

      <div className="scores" role="list" aria-label="Sub-scores out of 10">
        {SCORES.map((s) => {
          const v = pick[s.key] as number | null;
          return (
            <div className="score" role="listitem" key={s.key} title={`${s.name}: ${v ?? '—'} of 10 (weight ${s.weight})`}>
              <span className="top">
                <span className="name">{s.name}</span>
                <span className="val">{v == null ? '—' : Number(v).toFixed(v % 1 ? 1 : 0)}</span>
              </span>
              <span
                className="bar"
                role="meter"
                aria-label={`${s.name}`}
                aria-valuemin={0}
                aria-valuemax={10}
                aria-valuenow={v ?? 0}
              >
                <span style={{ width: `${Math.max(0, Math.min(10, v ?? 0)) * 10}%` }} />
              </span>
            </div>
          );
        })}
      </div>

      {(pick.hold_reason || pick.decision) && (
        <p className="pick-hold" style={{ margin: 0 }}>
          {pick.hold_reason
            ? `Held by the rule${needs ? ` (needs ${needs.replace('_', ' ')})` : ''}: ${pick.hold_reason}`
            : `${pick.decision?.by === 'rule' ? 'Rule' : 'Analyst'}: ${pick.decision?.reason ?? pick.decision?.decision}`}
        </p>
      )}

      {skipping ? (
        <form className="inline-form" onSubmit={skip} aria-label="Skip this pick">
          <span className="label">Why skip? (helps the analyst)</span>
          <div className="chips">
            {SKIP_REASONS.map((r) => (
              <button key={r} type="button" className="chip" aria-pressed={reason === r} onClick={() => setReason(r)}>
                {r}
              </button>
            ))}
          </div>
          <label className="sr-only" htmlFor={`skip-${pick.id}`}>Reason</label>
          <input id={`skip-${pick.id}`} className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Or say it in your words" />
          <div className="row">
            <button type="button" className="btn ghost" onClick={() => setSkipping(false)}>
              Cancel
            </button>
            <button type="submit" className="btn line" disabled={working} aria-busy={working}>
              {working && <Spinner />} Skip pick
            </button>
          </div>
        </form>
      ) : (
        <div className="pick-actions">
          <CharacterSeg value={slug} onChange={setSlug} label="Which character makes it" />
          <span className="grow" />
          <a className="btn ghost" href={pick.url} target="_blank" rel="noopener noreferrer" aria-label={`Open the original on ${platformName(pick.platform)} (new tab)`}>
            Original <ExternalLink aria-hidden="true" />
          </a>
          <div className="decide">
          <button type="button" className="btn line" onClick={() => setSkipping(true)} disabled={working}>
            Skip
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={approve}
            disabled={!slug || working}
            aria-busy={working}
            title={slug ? undefined : 'Choose a character first'}
          >
            {working && <Spinner />} {slug ? 'Approve' : 'Choose a character'}
          </button>
          </div>
        </div>
      )}
    </article>
  );
}

const STATUS_TONE: Record<string, string> = { approved: 'action', analysed: 'action', queued: 'live', made: 'live', skipped: '' };

function History() {
  const { data } = useStudio();
  if (!data || !data.history.length) return null;
  return (
    <Section id="pick-history" title="Decided" aside={`${data.history.length} picks`}>
      <div>
        {data.history.map((h) => (
          <div key={h.id} className="lib-item">
          <div className="lib-row" style={{ cursor: 'default' }}>
            <span className="l1">
              <Livery slug={h.character_slug} />
              <span className="hook">{h.hook ? `“${h.hook}”` : h.url}</span>
            </span>
            <span className={`tag ${STATUS_TONE[h.status] ?? ''}`}>{h.status}</span>
            <span className="l2">
              <span>score {h.total_score ?? '—'}</span>
              <span>{h.origin === 'owner' ? 'your link' : `by ${h.decision?.by ?? 'rule'}`}</span>
              {h.clip_id ? (
                <a href={h.clip_state === 'awaiting_approval' ? href('queue', h.clip_id) : href('library', h.clip_id)}>
                  clip {h.clip_state?.replace('_', ' ')}
                </a>
              ) : (
                <span>no clip yet</span>
              )}
              <a href={h.url} target="_blank" rel="noopener noreferrer">
                original <ExternalLink size={12} aria-hidden="true" />
              </a>
            </span>
          </div>
          </div>
        ))}
      </div>
    </Section>
  );
}
