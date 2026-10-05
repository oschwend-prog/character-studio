// Library: every clip ever made, filterable by character, platform and state, with its outlier badge,
// cost and where it went. Tap a row for the posts and their latest numbers.
import { ExternalLink } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { CharacterSwitcher, useCharacterChoice } from '../components/CharacterSwitcher';
import { Livery, OutlierBadge, Skeleton } from '../components/ui';
import { clipCode, formatCredits, formatViews, londonStamp, platformName } from '../lib/format';
import { useStudio } from '../lib/store';
import type { LibraryClip } from '../lib/types';

const STATES: { id: string; label: string; match: (s: string) => boolean }[] = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'posted', label: 'Posted', match: (s) => s === 'posted' },
  { id: 'scheduled', label: 'Scheduled', match: (s) => s === 'scheduled' || s === 'approved' },
  { id: 'waiting', label: 'Waiting', match: (s) => s === 'awaiting_approval' },
  { id: 'making', label: 'In the works', match: (s) => ['planned', 'generating', 'generated', 'qa_passed', 'mastered'].includes(s) },
  { id: 'out', label: 'Rejected / dropped', match: (s) => ['rejected', 'dropped', 'gen_failed', 'qa_failed'].includes(s) },
];
const STATE_TONE: Record<string, string> = {
  posted: 'live', scheduled: '', approved: '', awaiting_approval: 'action', rejected: 'alert', dropped: 'alert', gen_failed: 'alert', qa_failed: 'alert',
};

function Chips<T extends string>({ value, options, onChange, label }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="chips" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" className="chip" aria-pressed={value === o.id} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Library({ focus }: { focus: string | null }) {
  const { data } = useStudio();
  const [character, setCharacter, roster] = useCharacterChoice();
  const [platform, setPlatform] = useState<'all' | 'tiktok' | 'instagram'>('all');
  const [state, setState] = useState('all');
  const [open, setOpen] = useState<string | null>(focus);
  useEffect(() => setOpen(focus), [focus]);

  const rows = useMemo(() => {
    const st = STATES.find((s) => s.id === state) ?? STATES[0];
    return (data?.library ?? []).filter(
      (c) =>
        (character === 'all' || c.character_slug === character) &&
        (platform === 'all' || c.platforms.includes(platform)) &&
        st.match(c.state),
    );
  }, [data, character, platform, state]);

  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={300} />
      </div>
    );
  }
  const spent = rows.reduce((s, c) => s + (c.cost_credits ?? 0), 0);

  return (
    <div className="page stack">
      <div>
        <h1 className="h1">Library</h1>
        <p className="small muted num" style={{ margin: '6px 0 0' }}>
          {rows.length} of {data.library.length} clips · {formatCredits(spent)} spent on these
        </p>
      </div>
      <div className="filters">
        <CharacterSwitcher value={character} onChange={setCharacter} roster={roster} />
        <Chips label="Platform" value={platform} onChange={(v) => setPlatform(v)} options={[{ id: 'all', label: 'Any platform' }, { id: 'tiktok', label: 'TikTok' }, { id: 'instagram', label: 'Instagram' }]} />
        <Chips label="State" value={state} onChange={setState} options={STATES.map(({ id, label }) => ({ id, label }))} />
      </div>
      <div role="list" aria-label="Clips">
        {rows.length === 0 && (
          <div className="empty">
            <b>No clips match</b>
            <span className="small muted">Loosen a filter, or wait for the next daily run.</span>
          </div>
        )}
        {rows.map((c) => (
          <Row key={c.id} clip={c} open={open === c.id} onToggle={() => setOpen(open === c.id ? null : c.id)} />
        ))}
      </div>
    </div>
  );
}

function Row({ clip: c, open, onToggle }: { clip: LibraryClip; open: boolean; onToggle(): void }) {
  return (
    <div role="listitem" className={open ? 'lib-item open' : 'lib-item'}>
      <button type="button" className="lib-row" onClick={onToggle} aria-expanded={open}>
        <span className="l1">
          <Livery slug={c.character_slug} />
          <span className="hook">{c.hook ?? clipCode(c.id, c.character_slug)}</span>
        </span>
        <OutlierBadge x={c.outlier_x} />
        <span className="l2">
          <span>{clipCode(c.id, c.character_slug)}</span>
          <span className={`tag ${STATE_TONE[c.state] ?? ''}`}>{c.state.replace('_', ' ')}</span>
          <span>{c.mode}</span>
          <span>{c.platforms.length ? c.platforms.map(platformName).join(' + ') : 'not posted'}</span>
          {c.views != null && <span>{formatViews(c.views)} views</span>}
          <span>{formatCredits(c.cost_credits)}</span>
          <span>{londonStamp(c.posted_at ?? c.created_at)}</span>
        </span>
      </button>
      {open && (
        <div className="lib-detail">
          {c.caption && <span className="small muted">{c.caption}</span>}
          {c.reject_reason && <span className="small" style={{ color: 'var(--red)' }}>Reason: {c.reject_reason}</span>}
          {c.posts.length === 0 && <span className="small muted">No posts for this clip.</span>}
          {c.posts.map((p) => (
            <div className="lib-post" key={p.post_id}>
              <b style={{ color: 'var(--ink)' }}>{platformName(p.platform)}</b>
              <span>{p.handle}</span>
              <span className={`tag ${p.status === 'posted' ? 'live' : p.status === 'failed' || p.status === 'needs_check' ? 'alert' : ''}`}>{p.status.replace('_', ' ')}</span>
              <span className="num">{londonStamp(p.scheduled_for)}</span>
              {p.views != null && (
                <span className="num">
                  {formatViews(p.views)} views · {formatViews(p.likes)} likes · {formatViews(p.shares)} shares
                </span>
              )}
              {p.url && (
                <a href={p.url} target="_blank" rel="noopener noreferrer">
                  open <ExternalLink size={12} aria-hidden="true" />
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
