// Characters: one section per character (always shown, accounts or not): its picture, status, the two channel
// slots (a panel per account with its results, the Drop-in share and the posting autopilot switch with the lock
// rule; or "Not connected yet"), the go-live checklist and the pipeline of what is being made for it.
import { Check, ChevronRight, ExternalLink, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { MakeItSheet } from '../components/MakeIt';
import { Avatar, AutopilotSwitch, Livery, OutlierBadge, PlatformCode, Skeleton, characterName } from '../components/ui';
import { formatAge, formatCredits, formatViews, londonDate, londonStamp, platformName } from '../lib/format';
import { href, useNow } from '../lib/hooks';
import {
  channelSlots, goLiveChecklist, pipelineFor, type ChannelSlot, type Pipeline, type ProposedItem, type StageId,
} from '../lib/rules';
import { useStudio } from '../lib/store';
import type { Channel, Character, Pick as ViralPick } from '../lib/types';

export function Channels() {
  const { data } = useStudio();
  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={260} />
      </div>
    );
  }
  return (
    <div className="page stack">
      <div>
        <h1 className="h1">Characters</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          A hit is outlier 3× or more (views at 7 days against the channel’s own median). Autopilot unlocks after 6 approved posts.
        </p>
      </div>
      {data.characters.length === 0 && (
        <div className="panel empty">
          <b>No characters yet</b>
          <span className="small muted">
            Run <code>bin/studio seed</code>: it reads <code>characters/&lt;slug&gt;/refs.json</code> and puts each character here, with its accounts as they get created.
          </span>
        </div>
      )}
      {data.characters.map((c) => (
        <CharacterSection key={c.slug} character={c} />
      ))}
    </div>
  );
}

const STATUS_TAG: Record<string, string> = { live: 'live', designing: 'action', paused: '' };

function CharacterSection({ character: c }: { character: Character }) {
  const { data } = useStudio();
  if (!data) return null;
  const slots = channelSlots(c, data.channels);
  const mine = data.channels.filter((x) => x.character_slug === c.slug);
  const allConnectedAuto = mine.filter((x) => x.connected).every((x) => x.mode === 'auto');
  const titleId = `ch-${c.slug}`;
  return (
    <section className="char section" aria-labelledby={titleId}>
      <div className="char-head">
        <Avatar slug={c.slug} name={c.name} size={56} />
        <div className="who">
          <h2 className="h1" id={titleId} style={{ fontSize: 22 }}>
            {c.name}
          </h2>
          <span className="char-meta">
            <Livery slug={c.slug} />
            <span className={`tag ${STATUS_TAG[c.status] ?? ''}`}>{c.status}</span>
          </span>
        </div>
      </div>

      <div className="channels-grid stack" style={{ gap: 12 }}>
        {slots.map((slot) =>
          slot.channel ? (
            <ChannelPanel key={slot.platform} channel={slot.channel} allConnectedAuto={allConnectedAuto} />
          ) : (
            <NotConnected key={slot.platform} slot={slot} name={c.name} />
          ),
        )}
      </div>

      <Checklist character={c} />
      <PipelineView character={c} />
    </section>
  );
}

function NotConnected({ slot, name }: { slot: ChannelSlot; name: string }) {
  return (
    <article className="panel channel not-connected" aria-label={`${name} on ${platformName(slot.platform)}: not connected yet`}>
      <div className="channel-head">
        <PlatformCode platform={slot.platform} />
        <div className="who">
          <b>{slot.planned ?? 'no handle yet'}</b>
          <span className="small muted">{slot.planned ? `${platformName(slot.platform)} · planned handle` : platformName(slot.platform)}</span>
        </div>
        <span className="right">
          <span className="tag">not connected yet</span>
        </span>
      </div>
      <p className="small muted" style={{ margin: 0, padding: '0 14px 14px' }}>
        Create the account, connect it in Postiz, then tell Claude.
      </p>
    </article>
  );
}

function Checklist({ character }: { character: Character }) {
  const { items, done, total } = goLiveChecklist(character);
  const id = `check-${character.slug}`;
  return (
    <div className="checklist" role="group" aria-labelledby={id}>
      <div className="check-head">
        <h3 className="label" id={id}>
          Go-live checklist
        </h3>
        <span className="small muted num">
          {done} of {total}
        </span>
      </div>
      <ul className="check-list">
        {items.map((i) => (
          <li key={i.id} className={i.done ? 'done' : undefined}>
            {i.done ? <Check aria-hidden="true" /> : <X aria-hidden="true" />}
            <span className="txt">
              <span>
                {i.label}
                <span className="sr-only">{i.done ? ': done' : ': not yet'}</span>
              </span>
              <span className="small muted">{i.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const STAGES: { id: StageId; title: string; hint: string }[] = [
  { id: 'proposed', title: 'Proposed', hint: 'picks waiting or approved' },
  { id: 'production', title: 'In production', hint: 'being made' },
  { id: 'waiting', title: 'Waiting / scheduled', hint: 'for you, or booked' },
  { id: 'posted', title: 'Posted', hint: 'last 5' },
];

function PipelineView({ character }: { character: Character }) {
  const { data } = useStudio();
  const now = useNow(60_000);
  const [making, setMaking] = useState<ViralPick | null>(null);
  if (!data) return null;
  const pipe = pipelineFor(character.slug, data);
  const titleId = `pipe-${character.slug}`;
  return (
    <div className="pipeline" role="group" aria-labelledby={titleId}>
      <h3 className="label" id={titleId}>
        Pipeline
      </h3>
      {STAGES.map((st) => (
        <StageBlock key={st.id} id={`${character.slug}-${st.id}`} title={st.title} hint={st.hint} count={pipe[st.id].total} startOpen={(pipe.firstOpen ?? 'proposed') === st.id}>
          {st.id === 'proposed' && <ProposedList pipe={pipe} onMake={setMaking} />}
          {st.id === 'production' && <ProductionList pipe={pipe} now={now} />}
          {st.id === 'waiting' && <WaitingList pipe={pipe} />}
          {st.id === 'posted' && <PostedList pipe={pipe} />}
        </StageBlock>
      ))}
      {making && <MakeItSheet pick={making} onClose={() => setMaking(null)} />}
    </div>
  );
}

function StageBlock({
  id, title, hint, count, startOpen, children,
}: { id: string; title: string; hint: string; count: number; startOpen: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <details className="stage" open={open} onToggle={(e) => setOpen(e.currentTarget.open)} data-stage={id}>
      <summary>
        <ChevronRight className="chev" aria-hidden="true" />
        <span className="stage-title">{title}</span>
        <span className={`stage-count num${count ? ' on' : ''}`} aria-label={`${count} ${count === 1 ? 'item' : 'items'}`}>
          {count}
        </span>
        <span className="small muted stage-hint">{hint}</span>
      </summary>
      <div className="stage-body">{count === 0 ? <p className="small muted stage-empty">Nothing here right now.</p> : children}</div>
    </details>
  );
}

const MODE_LABEL = { dropin: 'Drop-in', recreate: 'Recreate' } as const;
const PART_LABEL = { cameo: 'Cameo', featured: 'Featured', star: 'Star' } as const;

/** "Drop-in · Featured", "Recreate" or "Analyst decides": how the owner said to loop him in. */
export function loopLabel(i: Pick<ProposedItem, 'ownerMode' | 'ownerPresence'>): string {
  if (!i.ownerMode) return 'Analyst decides';
  return i.ownerMode === 'dropin' ? `${MODE_LABEL.dropin} · ${PART_LABEL[i.ownerPresence ?? 'featured']}` : MODE_LABEL.recreate;
}

function ProposedList({ pipe, onMake }: { pipe: Pipeline; onMake(p: ViralPick): void }) {
  const { items, total } = pipe.proposed;
  return (
    <>
      <ul className="pipe-list">
        {items.map((i) => (
          <li key={i.id} className="pipe-row">
            <div className="pipe-main">
              <b className="pipe-hook">{i.hook ? `“${i.hook}”` : i.creator ?? i.url}</b>
              <div className="pipe-meta">
                <span className="tag num" title="Total score out of 100">score {i.score == null ? '—' : Math.round(i.score)}</span>
                <span>{platformName(i.platform)}</span>
                {i.creator && <span>{i.creator}</span>}
                <a href={i.url} target="_blank" rel="noopener noreferrer" aria-label={`Open the original on ${platformName(i.platform)} (new tab)`}>
                  original <ExternalLink size={12} aria-hidden="true" />
                </a>
              </div>
              <div className="pipe-meta">
                <span className={`tag ${i.status === 'new' ? 'action' : 'live'}`}>{i.held ? 'held' : i.status === 'new' ? 'waiting for you' : i.status}</span>
                <span className="tag" title="How to loop him in">{loopLabel(i)}</span>
              </div>
              {i.ownerNote && <p className="pipe-note small muted">Your note: “{i.ownerNote}”</p>}
            </div>
            {i.canMakeIt && i.pick && (
              <button type="button" className="btn primary" onClick={() => onMake(i.pick!)} aria-label={`Make it: ${i.hook ?? i.url}`}>
                Make it
              </button>
            )}
          </li>
        ))}
      </ul>
      {total > items.length && (
        <a className="small stage-more" href={href('picks')}>
          Showing {items.length} of {total} · all picks
        </a>
      )}
    </>
  );
}

function ProductionList({ pipe, now }: { pipe: Pipeline; now: number }) {
  const { items, total } = pipe.production;
  return (
    <>
      <ul className="pipe-list">
        {items.map((i) => (
          <li key={i.id} className="pipe-row">
            <div className="pipe-main">
              <b className="pipe-hook">{i.hook ? `“${i.hook}”` : 'untitled clip'}</b>
              <div className="pipe-meta">
                <span className={`tag${i.failed ? ' alert' : ' action'}`}>{i.state.replace('_', ' ')}</span>
                <span>{formatAge(i.createdAt, now)}</span>
                <span className="num">{formatCredits(i.credits)}</span>
              </div>
            </div>
          </li>
        ))}
      </ul>
      {total > items.length && <span className="small muted stage-more">Showing {items.length} of {total}</span>}
    </>
  );
}

function WaitingList({ pipe }: { pipe: Pipeline }) {
  const { items, total } = pipe.waiting;
  return (
    <>
      <ul className="pipe-list">
        {items.map((i) => (
          <li key={i.id} className="pipe-row">
            <div className="pipe-main">
              <b className="pipe-hook">{i.hook ? `“${i.hook}”` : 'untitled clip'}</b>
              <div className="pipe-meta">
                {i.kind === 'awaiting_approval' ? (
                  <>
                    <span className="tag action">needs you</span>
                    <span>{i.at ? `would go ${londonStamp(i.at)}` : 'no slot yet'}</span>
                  </>
                ) : (
                  <>
                    <span className="tag live">scheduled</span>
                    <span>{i.at ? londonStamp(i.at) : 'no slot yet'}</span>
                  </>
                )}
                {i.platforms.length > 0 && <span>{i.platforms.map(platformName).join(' + ')}</span>}
              </div>
              {i.blocked && <p className="pipe-note small error-text">Can’t be approved yet: {i.blocked}</p>}
            </div>
            <a className="btn line" href={i.kind === 'awaiting_approval' ? href('queue', i.id) : href('library', i.id)}>
              {i.kind === 'awaiting_approval' ? 'Review' : 'Open'}
            </a>
          </li>
        ))}
      </ul>
      {total > items.length && <span className="small muted stage-more">Showing {items.length} of {total}</span>}
    </>
  );
}

function PostedList({ pipe }: { pipe: Pipeline }) {
  const { items } = pipe.posted;
  return (
    <ul className="pipe-list">
      {items.map((i) => (
        <li key={i.id} className="pipe-row">
          <div className="pipe-main">
            <b className="pipe-hook">{i.hook ? `“${i.hook}”` : 'untitled clip'}</b>
            <div className="pipe-meta">
              <span>{i.postedAt ? londonDate(i.postedAt) : 'posted'}</span>
              {i.platforms.length > 0 && <span>{i.platforms.map(platformName).join(' + ')}</span>}
              <span className="num">{formatViews(i.views)} views</span>
              <OutlierBadge x={i.outlierX} />
            </div>
          </div>
          <a className="btn line" href={href('library', i.id)} aria-label={`Open ${i.hook ?? 'this clip'} in the library`}>
            Library
          </a>
        </li>
      ))}
    </ul>
  );
}

function ChannelPanel({ channel: c, allConnectedAuto }: { channel: Channel; allConnectedAuto: boolean }) {
  const { backend, run, busy } = useStudio();
  const key = `mode-${c.account_id}`;
  const ratioPct = Math.round((c.dropin_ratio ?? 0) * 100);
  const sharePct = Math.round((c.dropin_share ?? 0) * 100);
  return (
    <article className="panel channel" aria-label={`${characterName(c.character_slug)} on ${platformName(c.platform)}`}>
      <div className="channel-head">
        <PlatformCode platform={c.platform} />
        <div className="who">
          <b>{c.handle ?? 'no handle yet'}</b>
          <span className="small muted">{platformName(c.platform)}</span>
        </div>
        <span className="right">
          {c.connected ? <span className="tag live">connected</span> : <span className="tag">not linked</span>}
        </span>
      </div>
      <div className="kv">
        <div>
          <span className="label">Posts</span>
          <span className="v">{c.posts_posted}</span>
        </div>
        <div>
          <span className="label">Views 7 d</span>
          <span className="v">{formatViews(c.views_7d)}</span>
        </div>
        <div>
          <span className="label">Median ×</span>
          <span className="v">
            <OutlierBadge x={c.median_outlier_x} />
          </span>
        </div>
        <div>
          <span className="label">Hit rate</span>
          <span className="v">{c.hit_rate == null ? '—' : `${Math.round(c.hit_rate * 100)}%`}</span>
        </div>
        <div>
          <span className="label">Follows</span>
          <span className="v">{formatViews(c.follows)}</span>
        </div>
        <div>
          <span className="label">Bar</span>
          <span className="v" style={{ fontSize: 14 }}>{c.bar_status ?? 'not yet'}</span>
        </div>
      </div>
      <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }} className="small">
          <span className="muted">Drop-in, last 10 posts</span>
          <span className="num">
            {ratioPct}% <span className="muted">of {sharePct}% share</span>
          </span>
        </div>
        <div className="meter" role="meter" aria-label="Drop-in ratio against share" aria-valuemin={0} aria-valuemax={100} aria-valuenow={ratioPct} style={{ height: 8 }}>
          <span className="fill" style={{ width: `${ratioPct}%`, background: 'var(--ink-2)' }} />
          <span className="tick" style={{ left: `${sharePct}%` }} title={`Share ${sharePct}%`} />
        </div>
        <span className="small muted">
          {c.posts_scheduled ? `${c.posts_scheduled} scheduled` : 'nothing scheduled'}
          {c.posts_problem ? ` · ${c.posts_problem} need a look` : ''}
          {c.next_slot ? ` · next slot ${londonStamp(c.next_slot)}` : ''}
        </span>
      </div>
      <div style={{ borderTop: '1px solid var(--rule)' }}>
        <AutopilotSwitch
          channel={c}
          allConnectedAuto={allConnectedAuto}
          busy={busy.has(key)}
          onToggle={(mode) =>
            run(key, () => backend.setAccountMode(c.account_id, mode), mode === 'auto' ? `Autopilot on for ${c.handle}` : `Autopilot off for ${c.handle}`)
          }
        />
      </div>
    </article>
  );
}
