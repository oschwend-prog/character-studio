// Viral Picks: the Scanner card and "How we scan", then the proposed videos by character (Biscuit, Reginald, then the unassigned ones), each
// section grouped by category (Broke the internet, Viral now, Up and coming, Ready to drop in) or by theme, best first with
// the Genjutsu gallery as the backup. Each card says plainly what the video is, then Make it / Skip; a paste box for the
// owner's own links; the decided picks with what they became. A switch at the top shows the same picks as one sortable Long list
// instead (components/LongList.tsx); a row opens the very same card in a sheet, so Make it and Skip work exactly as on the cards.
import { Clapperboard, Crown, ExternalLink, Flame, Link2, Plus, TrendingUp } from 'lucide-react';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { CharacterSwitcher, useCharacterChoice } from '../components/CharacterSwitcher';
import { HowWeScan } from '../components/HowWeScan';
import { LongList } from '../components/LongList';
import { MakeItSheet } from '../components/MakeIt';
import { PickThumb } from '../components/PickThumb';
import { ScannerCard } from '../components/Scanner';
import { Avatar, Flap, Livery, Section, Sheet, Skeleton, Spinner, characterName } from '../components/ui';
import { pickFacts } from '../lib/analyst';
import { formatViews, outlierBadge, platformName } from '../lib/format';

const formatOutlier = (x: number) => outlierBadge(x).label;
import { href, useNow, useRoute } from '../lib/hooks';
import { PICKS_VIEW_KEY, picksView, type PicksView } from '../lib/longlist';
import {
  TIERS, TIER_HINTS, TIER_LABELS, canonicalVideoUrl, groupPicksByCharacter, modeLine, tierCounts, tierOf,
  type PickSection,
} from '../lib/rules';
import { useStudio } from '../lib/store';
import type { Pick, Tier } from '../lib/types';

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

const TIER_ICON: Record<Tier, typeof Flame> = { iconic: Crown, viral_now: Flame, rising: TrendingUp, gallery: Clapperboard };

const storedView = (): string | null => {
  try {
    return window.localStorage.getItem(PICKS_VIEW_KEY);
  } catch {
    return null; // blocked site data: the page still works, it just forgets the choice
  }
};

/** Cards or Long list: a `?view=` deep link, else the viewer's last choice (localStorage, guarded), else the cards. */
function usePicksView(): [PicksView, (v: PicksView) => void] {
  const { query } = useRoute();
  const [view, setView] = useState<PicksView>(() => picksView(query, storedView()));
  useEffect(() => setView(picksView(query, storedView())), [query]);
  const choose = (v: PicksView) => {
    setView(v);
    try {
      window.localStorage.setItem(PICKS_VIEW_KEY, v);
    } catch {
      /* not remembered */
    }
  };
  return [view, choose];
}

export function Picks() {
  const { data } = useStudio();
  const now = useNow(60_000);
  const [character, setCharacter, roster] = useCharacterChoice();
  const [tier, setTier] = useState<Tier | 'all'>('all');
  const [view, setView] = usePicksView();
  const [openId, setOpenId] = useState<string | null>(null);
  const [making, setMaking] = useState<Pick | null>(null);
  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={120} />
        <Skeleton h={300} />
      </div>
    );
  }
  const inScope = data.picks.filter((p) => character === 'all' || p.character_slug === character);
  const counts: Record<string, number> = { all: data.picks.length };
  for (const c of roster) counts[c.slug] = data.picks.filter((p) => p.character_slug === c.slug).length;
  const tiers = tierCounts(inScope, now);
  const sections = groupPicksByCharacter(data.picks, roster, { now, character, tier });
  const shown = sections.reduce((n, s) => n + s.picks.length, 0);
  const openPick = openId ? data.picks.find((p) => p.id === openId) ?? null : null; // gone once decided: the sheet closes
  const header = (
    <>
      <div>
        <h1 className="h1">Viral Picks</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          Best first, real viral clips before the Genjutsu gallery. The standing rule already approved anything 80+ with feasibility 7+; these wait for a call.
        </p>
      </div>
      <div className="seg view-switch" role="group" aria-label="Show the picks as">
        {(['cards', 'list'] as const).map((v) => (
          <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}>
            {v === 'cards' ? 'Cards' : 'Long list'}
          </button>
        ))}
      </div>
    </>
  );
  if (view === 'list') {
    return (
      <div className="page stack">
        {header}
        <LongList picks={data.picks} roster={roster} character={character} onCharacter={setCharacter} now={now} onOpen={(p) => setOpenId(p.id)} />
        {openPick && (
          <Sheet title={openPick.character_name ? `${openPick.character_name}’s pick` : 'The pick'} onClose={() => setOpenId(null)}>
            <PickCard
              pick={openPick}
              onMakeIt={() => {
                setOpenId(null);
                setMaking(openPick);
              }}
            />
            <div className="sheet-actions">
              <button type="button" className="btn ghost" onClick={() => setOpenId(null)}>
                Close
              </button>
            </div>
          </Sheet>
        )}
        {making && <MakeItSheet pick={making} onClose={() => setMaking(null)} />}
      </div>
    );
  }
  return (
    <div className="page stack">
      {header}
      <ScannerCard />
      <HowWeScan />
      <PasteBox />
      <div className="pick-filters stack" style={{ gap: 10 }}>
        <CharacterSwitcher value={character} onChange={setCharacter} roster={roster} counts={counts} />
        <div className="chips tier-chips" role="group" aria-label="Category">
          {(['all', ...TIERS] as const).map((t) => (
            <button key={t} type="button" className={`chip tier-${t}`} aria-pressed={tier === t} onClick={() => setTier(t)} title={t === 'all' ? undefined : TIER_HINTS[t]}>
              {t === 'all' ? 'All' : TIER_LABELS[t]} <span className="num count">{tiers[t]}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="stack" id="new-picks" style={{ gap: 22 }} aria-label={`${shown} proposed videos`}>
        {sections.map((sec) => (
          <CharacterPicks key={sec.slug ?? 'unassigned'} section={sec} />
        ))}
        {data.picks.length === 0 && (
          <div className="panel empty">
            <b>No picks waiting</b>
            <span className="muted small">The daily scan files new ones every day. Paste a link above to add your own.</span>
          </div>
        )}
      </div>
      <History />
    </div>
  );
}

/** One character's section: its picture, name and count, then its picks grouped by category or by theme. */
function CharacterPicks({ section }: { section: PickSection<Pick> }) {
  const [by, setBy] = useState<'category' | 'theme'>('category');
  const slug = section.slug;
  const titleId = `sec-${slug ?? 'unassigned'}`;
  return (
    <section className={`pick-sec ${slug ?? 'none'}`} aria-labelledby={titleId} data-char={slug ?? 'none'}>
      <header className="pick-sec-head">
        {slug ? <Avatar slug={slug} name={section.name} size={40} /> : <Livery slug={null} />}
        <h2 className="h2" id={titleId}>{section.name}</h2>
        <span className="stage-count num on" aria-label={`${section.picks.length} proposed`}>{section.picks.length}</span>
        {section.picks.length > 1 && (
          <div className="seg group-by" role="group" aria-label={`Group ${section.name}'s picks by`}>
            {(['category', 'theme'] as const).map((g) => (
              <button key={g} type="button" aria-pressed={by === g} onClick={() => setBy(g)}>
                {g === 'category' ? 'Category' : 'Theme'}
              </button>
            ))}
          </div>
        )}
      </header>
      {section.picks.length === 0 ? (
        <p className="small muted pick-sec-empty">Nothing proposed for {section.name} right now: the next scan files more.</p>
      ) : by === 'category' ? (
        section.tiers.map((g) => {
          const Icon = TIER_ICON[g.tier];
          return (
            <GroupBlock key={g.tier} id={`${titleId}-${g.tier}`} icon={<Icon size={16} aria-hidden="true" />} label={g.label} hint={TIER_HINTS[g.tier]} count={g.picks.length}>
              {g.picks.map((p) => (
                <PickCard key={p.id} pick={p} />
              ))}
            </GroupBlock>
          );
        })
      ) : (
        section.themes.map((g) => (
          <GroupBlock key={g.label} id={`${titleId}-${g.label}`} label={g.label} count={g.picks.length}>
            {g.picks.map((p) => (
              <PickCard key={p.id} pick={p} />
            ))}
          </GroupBlock>
        ))
      )}
    </section>
  );
}

function GroupBlock({ id, icon, label, hint, count, children }: { id: string; icon?: ReactNode; label: string; hint?: string; count: number; children: ReactNode }) {
  return (
    <div className="pick-group" role="group" aria-labelledby={id}>
      <h3 className="pick-group-head" id={id} title={hint}>
        {icon}
        <span>{label}</span>
        <span className="num count">{count}</span>
      </h3>
      <div className="picks-grid stack" style={{ gap: 12 }}>
        {children}
      </div>
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

/** One proposed pick. `onMakeIt`: who opens the Make-it sheet (the long list's sheet hands it over; the card opens its own). */
function PickCard({ pick, onMakeIt }: { pick: Pick; onMakeIt?: () => void }) {
  const { backend, run, busy } = useStudio();
  const now = useNow(60_000);
  const slug = pick.character_slug;
  const [making, setMaking] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [reason, setReason] = useState('');
  const key = `pick-${pick.id}`;
  const working = busy.has(key);
  const needs = Array.isArray(pick.needs) ? pick.needs.join(', ') : pick.needs;
  const titleId = `pick-${pick.id}-t`;
  const { tier, derived } = tierOf(pick, now);
  const TierIcon = TIER_ICON[tier];
  const facts = pickFacts(pick, now);
  const hasFacts = Boolean(facts.posted || facts.velocity || facts.engagement || facts.shares || facts.saturation);
  const why = pick.hold_reason
    ? `Held by the rule${needs ? ` (needs ${needs.replace('_', ' ')})` : ''}: ${pick.hold_reason}`
    : pick.decision
      ? `${pick.decision.by === 'rule' ? 'Rule' : 'Analyst'}: ${pick.decision.reason ?? pick.decision.decision}`
      : null;

  const skip = (e: FormEvent) => {
    e.preventDefault();
    void run(key, () => backend.decidePick(pick.id, 'skip', reason.trim() || null, null), 'Skipped');
  };

  return (
    <article className="panel pick" data-char={slug ?? 'none'} data-tier={tier} aria-labelledby={titleId}>
      <div className="pick-layout">
        <PickThumb pick={pick} />
        <div className="pick-main">
          <div className="pick-badges">
            <span className={`tier-badge tier-${tier}`} title={`${TIER_HINTS[tier]}${derived ? ' (worked out from the numbers)' : ''}`}>
              <TierIcon size={13} aria-hidden="true" /> {TIER_LABELS[tier]}
            </span>
            {pick.theme && <span className="tag theme-chip" title="The scan theme it matched">{pick.theme}</span>}
            {slug && <Livery slug={slug} />}
          </div>
          <h3 className="pick-hook" id={titleId} style={{ margin: 0 }}>
            {pick.hook ? `“${pick.hook}”` : pick.creator_handle ?? pick.url}
          </h3>
          <p className="pick-mode" style={{ margin: 0 }}>
            {modeLine(pick)}
            {!slug && pick.intended_character ? ` · for ${pick.intended_character} (not built yet)` : ''}
          </p>
          <div className="pick-meta">
            <span>{platformName(pick.platform)}</span>
            {pick.creator_handle && <span>{pick.creator_handle}</span>}
            {pick.views != null && <span className="num">{formatViews(pick.views)} views</span>}
            {pick.outlier_x != null && (
              <span className="tag num" title="Views against the creator's own median">
                {formatOutlier(pick.outlier_x)} their median
              </span>
            )}
          </div>
          {hasFacts && (
            <div className="pick-facts" aria-label="How the video is doing">
              {facts.posted && <span title="When the video was posted">{facts.posted}</span>}
              {facts.velocity && <span className="num" title="Views per day since it was posted">{facts.velocity}</span>}
              {facts.engagement && <span className="num" title="Likes, comments, shares and saves against views">{facts.engagement}</span>}
              {facts.shares && <span className="num" title="Shares against views">{facts.shares}</span>}
              {facts.saturation && <span title="Similar videos found in the last 7 days">{facts.saturation}</span>}
            </div>
          )}
        </div>
        <div className="pick-total">
          <Flap text={pick.total_score == null ? '--' : String(Math.round(pick.total_score))} label={`Total score ${pick.total_score ?? 'not scored'} of 100`} />
          <span className="label">score</span>
        </div>
      </div>

      {pick.concept && <p className="pick-concept" style={{ margin: 0 }}>{pick.concept}</p>}
      {facts.matches.length > 0 && (
        <p className="pick-matches">
          <b>Matches:</b> {facts.matches.join(' · ')}
        </p>
      )}
      {facts.why && (
        <p className="pick-why">
          <b>Why:</b> {facts.why}
        </p>
      )}
      {why && <p className="pick-hold" style={{ margin: 0 }}>{why}</p>}
      {facts.check && (
        <div className="clip-check" role="group" aria-label="Clip check">
          <span className="label">Clip check</span>
          <ul className="chips">
            {facts.check.map((c) => (
              <li key={c.text} className={`tag check-${c.tone}`}>
                {c.text}
              </li>
            ))}
          </ul>
          {facts.checkNotes && <span className="small muted">{facts.checkNotes}</span>}
        </div>
      )}

      <details className="pick-scores">
        <summary className="small muted">Sub-scores</summary>
        <div className="scores" role="list" aria-label="Sub-scores out of 10">
          {SCORES.map((sc) => {
            const v = pick[sc.key] as number | null;
            return (
              <div className="score" role="listitem" key={sc.key} title={`${sc.name}: ${v ?? '—'} of 10 (weight ${sc.weight})`}>
                <span className="top">
                  <span className="name">{sc.name}</span>
                  <span className="val">{v == null ? '—' : Number(v).toFixed(v % 1 ? 1 : 0)}</span>
                </span>
                <span className="bar" role="meter" aria-label={`${sc.name}`} aria-valuemin={0} aria-valuemax={10} aria-valuenow={v ?? 0}>
                  <span style={{ width: `${Math.max(0, Math.min(10, v ?? 0)) * 10}%` }} />
                </span>
              </div>
            );
          })}
        </div>
      </details>

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
          <span className="grow" />
          {/^https:/.test(pick.url) && (
            <a className="btn ghost" href={pick.url} target="_blank" rel="noopener noreferrer" aria-label={`Open the original on ${platformName(pick.platform)} (new tab)`}>
              Original <ExternalLink aria-hidden="true" />
            </a>
          )}
          <div className="decide">
            <button type="button" className="btn line" onClick={() => setSkipping(true)} disabled={working}>
              Skip
            </button>
            <button type="button" className="btn primary" onClick={() => (onMakeIt ? onMakeIt() : setMaking(true))} disabled={working} aria-busy={working} aria-haspopup="dialog">
              {working && <Spinner />} Make it
            </button>
          </div>
        </div>
      )}
      {making && <MakeItSheet pick={pick} onClose={() => setMaking(false)} />}
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
