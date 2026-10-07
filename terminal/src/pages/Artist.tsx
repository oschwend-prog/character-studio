// A character's own page (`#/artist/<slug>`, owner 2026-10-06), reached from the Characters page and from his name: who he is
// (his sheets, look and wardrobe, motion and signature move, catchphrase, voice, gadgets with their viral job, the swap rule; from
// his bible through src/generated/artists.json) and how he is doing: all his videos grouped Live (posted, with views), Scheduled
// and In the making, then at the bottom his accounts' results and autopilot (a panel per channel), his traits and the go-live
// checklist (terminal v2, owner 2026-10-07). From what the terminal already loads. The established classes only: the Characters
// card's head, Section, the stage cards, the kv grid, the pipeline rows, the trait chips and the checklist rows.
import { Check, ChevronLeft, ChevronRight, ExternalLink, X } from 'lucide-react';
import type { ReactNode } from 'react';
import generated from '../generated/artists.json';
import { ChannelPanel, Checklist } from '../components/ChannelPanel';
import { TraitsCard } from '../components/TraitsCard';
import { Avatar, Livery, OutlierBadge, PlatformCode, Section, Skeleton } from '../components/ui';
import {
  artistAccounts, artistGroups, artistVideos, findArtist, inlineParts, swapLine, type Artist as ArtistCard, type ArtistItem, type ArtistVideo,
} from '../lib/artist';
import { formatCredits, formatViews, londonDate, londonStamp, platformName } from '../lib/format';
import { href, useNow } from '../lib/hooks';
import { nameOf } from '../lib/roster';
import { channelSlots } from '../lib/rules';
import { useStudio } from '../lib/store';

const ARTISTS = (generated as unknown as { artists: ArtistCard[] }).artists;
const STATUS_TAG: Record<string, string> = { live: 'live', designing: 'action', paused: '' };
const POSTED_SHOWN = 5;

/** A bible line with its bold and code kept. */
function Inline({ text }: { text: string }) {
  return (
    <>
      {inlineParts(text).map((p, i) =>
        p.kind === 'strong' ? <b key={i}>{p.text}</b> : p.kind === 'code' ? <code key={i}>{p.text}</code> : <span key={i}>{p.text}</span>,
      )}
    </>
  );
}

function Items({ items, label }: { items: ReadonlyArray<ArtistItem>; label?: string }) {
  if (!items.length) return null;
  return (
    <ul className="how-list plain" aria-label={label}>
      {items.map((it, i) => (
        <li key={i}>
          <span>
            <Inline text={it.text} />
          </span>
          {it.children?.length ? <Items items={it.children} /> : null}
        </li>
      ))}
    </ul>
  );
}

/** A collapsible card, the markup of the Traits card. */
function Stage({ title, hint, open, children }: { title: string; hint?: string; open?: boolean; children: ReactNode }) {
  return (
    <details className="stage" open={open}>
      <summary>
        <ChevronRight className="chev" aria-hidden="true" />
        <span className="stage-title">{title}</span>
        {hint && <span className="small muted stage-hint">{hint}</span>}
      </summary>
      <div className="stage-body traits-body">{children}</div>
    </details>
  );
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="trait">
      <span className="label">{label}</span>
      {children}
    </div>
  );
}

const nothing = <p className="small muted" style={{ margin: 0 }}>Not in his bible yet.</p>;

export function Artist({ slug }: { slug: string | null }) {
  const { data } = useStudio();
  const now = useNow(60_000);
  const back = (
    <a className="link" href={href('characters')}>
      <ChevronLeft size={16} aria-hidden="true" /> Characters
    </a>
  );
  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={120} />
        <Skeleton h={260} />
      </div>
    );
  }
  const card = findArtist(slug, ARTISTS);
  const character = (slug && data.characters.find((c) => c.slug === slug)) || null;
  if (!slug || (!card && !character)) {
    return (
      <div className="page stack">
        {back}
        <div className="panel empty">
          <b>No character {slug ? `“${slug}”` : 'chosen'}</b>
          <span className="small muted">
            A character gets his page from <code>characters/&lt;slug&gt;/</code> (refs.json and bible.md) and <code>bin/studio seed</code>.
          </span>
        </div>
      </div>
    );
  }
  const name = character?.name ?? card?.name ?? nameOf(slug);
  const status = character?.status ?? card?.status ?? 'designing';
  const videos = artistVideos(slug, data, now);
  const accounts = artistAccounts(card, character);
  const channels = character ? channelSlots(character, data.channels).flatMap((c) => (c.channel ? [c.channel] : [])) : [];
  const allConnectedAuto = channels.filter((c) => c.connected).every((c) => c.mode === 'auto');
  const titleId = `artist-${slug}`;

  return (
    <div className="page stack">
      {back}
      <section className="char section" aria-labelledby={titleId}>
        <div className="char-head">
          <Avatar slug={slug} name={name} size={72} />
          <div className="who">
            <h1 className="h1" id={titleId}>
              {name}
            </h1>
            <span className="char-meta">
              <Livery slug={slug} />
              <span className={`tag ${STATUS_TAG[status] ?? ''}`}>{status}</span>
              {card?.edition && <span className="tag">{card.edition} edition</span>}
            </span>
          </div>
        </div>
        {card?.concept && (
          <p className="small muted" style={{ margin: 0 }}>
            <Inline text={card.concept} />
          </p>
        )}
      </section>

      <Sheets card={card} name={name} />
      <ArtistVideosBlock videos={videos} name={name} slug={slug} />

      <Section title="Catchphrase" id={`${titleId}-catch`}>
        {card?.catchphrase.line ? (
          <>
            <p className="artist-quote">“{card.catchphrase.line}”</p>
            <Items items={card.catchphrase.notes} label="More about the catchphrase" />
          </>
        ) : (
          nothing
        )}
      </Section>

      <Stage title="Look and wardrobe" open>
        {card?.look.length ? <Items items={card.look} label="Look, head to toe" /> : nothing}
        {card?.wardrobe.signature.length ? (
          <Group label="Signature outfit">
            <Items items={card.wardrobe.signature} />
          </Group>
        ) : null}
        {card?.wardrobe.capsule.length ? (
          <Group label="Capsule">
            <Items items={card.wardrobe.capsule} />
          </Group>
        ) : null}
      </Stage>

      <Stage title="Motion and signature move">
        {card?.signature_move.text && (
          <Group label="Signature move">
            <p className="small" style={{ margin: 0 }}>
              <Inline text={card.signature_move.text} />
            </p>
            <Items items={card.signature_move.notes} />
          </Group>
        )}
        {card?.motion.length ? (
          <Group label="Motion">
            <Items items={card.motion} />
          </Group>
        ) : (
          !card?.signature_move.text && nothing
        )}
      </Stage>

      <Stage title="How he talks">
        <Voice card={card} />
      </Stage>

      <Stage title="Gadgets" hint="and the viral job of each">
        {card?.gadgets.length ? (
          <ul className="trait-chips" aria-label={`${name}’s gadgets`}>
            {card.gadgets.map((g) => (
              <li key={g.name} className="trait-chip has-hint">
                <span>{g.name}</span>
                <span className="chip-hint">{[g.status, g.job].filter(Boolean).join(' · ')}</span>
              </li>
            ))}
          </ul>
        ) : (
          nothing
        )}
      </Stage>

      <Section title="Swap rule" id={`${titleId}-swap`}>
        {card && swapLine(card.swap.stars) && (
          <span className="char-meta">
            <span className="tag">{swapLine(card.swap.stars)}</span>
            {card.swap.noun && <span className="small muted">as “the {card.swap.noun}”</span>}
          </span>
        )}
        {card?.swap.text ? (
          <p className="small" style={{ margin: 0 }}>
            <Inline text={card.swap.text} />
          </p>
        ) : (
          nothing
        )}
      </Section>

      <Section title="Accounts" id={`${titleId}-accounts`}>
        <ul className="check-list" aria-label={`${name}’s accounts`}>
          {accounts.map((a) => (
            <li key={a.platform} className={a.state === 'live' ? 'done' : undefined}>
              {a.state === 'live' ? <Check aria-hidden="true" /> : <X aria-hidden="true" />}
              <PlatformCode platform={a.platform} />
              <span className="txt">
                <span>{a.handle ?? 'no handle yet'}</span>
                <span className="small muted">
                  {platformName(a.platform)} ·{' '}
                  {a.state === 'live' ? 'connected in Postiz' : a.state === 'linked' ? 'created, not connected in Postiz' : 'planned, not created yet'}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </Section>

      {character && (
        <>
          {channels.length > 0 && (
            <Section title="Channels" id={`${titleId}-channels`} aside="results and autopilot">
              <p className="small muted" style={{ margin: 0 }}>
                A hit is outlier 3× or more (views at 7 days against the channel’s own median). Autopilot unlocks after 6 approved posts.
              </p>
              <div className="channels-grid stack" style={{ gap: 12 }}>
                {channels.map((c) => (
                  <ChannelPanel key={c.account_id} channel={c} allConnectedAuto={allConnectedAuto} />
                ))}
              </div>
            </Section>
          )}
          <TraitsCard character={character} />
          <Checklist character={character} />
        </>
      )}
    </div>
  );
}

function Sheets({ card, name }: { card: ArtistCard | null; name: string }) {
  const turnaround = card?.images.turnaround ?? card?.images.turnaround_url ?? null;
  return (
    <Section title="Sheets" id="artist-sheets">
      {turnaround ? (
        <a className="artist-sheet" href={card?.images.turnaround_url ?? turnaround} target="_blank" rel="noopener noreferrer">
          <img
            src={turnaround}
            alt={`${name}: turnaround sheet (front, three-quarter, side, back)`}
            loading="lazy"
            decoding="async"
            onError={(e) => {
              const img = e.currentTarget;
              const cdn = card?.images.turnaround_url;
              if (cdn && img.src !== cdn) img.src = cdn; // the build's copy is missing: the Higgsfield original
            }}
          />
        </a>
      ) : (
        nothing
      )}
      {card?.images.spec && (
        <details className="stage">
          <summary>
            <ChevronRight className="chev" aria-hidden="true" />
            <span className="stage-title">Spec sheet</span>
            <span className="small muted stage-hint">one page, tap to open</span>
          </summary>
          <div className="stage-body traits-body">
            <a className="artist-sheet spec" href={card.images.spec} target="_blank" rel="noopener noreferrer">
              <img src={card.images.spec} alt={`${name}: spec sheet`} loading="lazy" decoding="async" />
            </a>
            <a className="link" href={card.images.spec} target="_blank" rel="noopener noreferrer">
              Open the whole sheet <ExternalLink size={12} aria-hidden="true" />
            </a>
          </div>
        </details>
      )}
    </Section>
  );
}

function Voice({ card }: { card: ArtistCard | null }) {
  if (!card?.voice.items.length && !card?.voice.preset) return nothing;
  const v = card.voice;
  return (
    <>
      {(v.preset || v.sample_url) && (
        <span className="char-meta">
          {v.preset && <span className="tag">Higgsfield voice {v.preset}</span>}
          {v.sample_url && (
            <a className="link" href={v.sample_url} target="_blank" rel="noopener noreferrer">
              Sample <ExternalLink size={12} aria-hidden="true" />
            </a>
          )}
        </span>
      )}
      {v.sample_url && <audio controls preload="none" src={v.sample_url} style={{ width: '100%' }} aria-label={`${card.name}’s voice sample`} />}
      <Items items={v.items} label="How he talks" />
    </>
  );
}

function VideoRow({ v }: { v: ArtistVideo }) {
  // where each kind of his videos opens: a drop before Make it in Clips, a clip being made or waiting for your OK in Videos,
  // a scheduled or posted one in the Characters list (All videos)
  const to =
    v.route === 'works' ? href('clips') : v.route === 'making' ? href('videos') : v.route === 'queue' ? href('videos', v.id) : href('characters', 'all', { clip: v.id });
  return (
    <li className="pipe-row">
      <div className="pipe-main">
        <b className="pipe-hook">{v.title}</b>
        <div className="pipe-meta">
          {v.at !== undefined ? (
            <>
              <span className={`tag${v.where === 'Scheduled' ? ' live' : ''}`}>{v.where}</span>
              <span className="num">{v.at ? londonStamp(v.at) : 'no slot yet'}</span>
              {v.platforms && v.platforms.length > 0 && <span>{v.platforms.map(platformName).join(' + ')}</span>}
            </>
          ) : v.route === 'library' ? (
            <>
              <span>{londonDate(v.where)}</span>
              <span className="num">{formatViews(v.views)} views</span>
              <OutlierBadge x={v.outlierX} />
            </>
          ) : (
            <span className={`tag ${v.route === 'queue' ? 'action' : 'live'}`}>{v.where}</span>
          )}
        </div>
      </div>
      <a className="btn line" href={to} aria-label={`Open ${v.title}`}>
        Open
      </a>
    </li>
  );
}

function VideoGroup({ id, title, rows, total, empty, name }: { id: string; title: string; rows: ReadonlyArray<ArtistVideo>; total: number; empty: ReactNode; name: string }) {
  return (
    <div className="pipeline" role="group" aria-labelledby={id}>
      <div className="char-meta">
        <h3 className="label" id={id}>
          {title}
        </h3>
        <span className={`stage-count num${total ? ' on' : ''}`} aria-label={`${total} ${total === 1 ? 'video' : 'videos'}`}>
          {total}
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="small muted" style={{ margin: 0 }}>{empty}</p>
      ) : (
        <ul className="pipe-list" aria-label={`${name}’s ${title.toLowerCase()} videos`}>
          {rows.map((v) => (
            <VideoRow key={`${v.route}-${v.id}`} v={v} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ArtistVideosBlock({ videos, name, slug }: { videos: ReturnType<typeof artistVideos>; name: string; slug: string }) {
  const s = videos.stats;
  const g = artistGroups(videos);
  const all = href('characters', 'all', { c: slug });
  return (
    <Section title="Videos" id="artist-videos" aside={<a href={all}>All his videos →</a>}>
      <div className="panel">
        <div className="kv" style={{ borderTop: 0, borderBottom: 0 }}>
          <div>
            <span className="label">In the making</span>
            <span className="v">{g.making.length}</span>
          </div>
          <div>
            <span className="label">Scheduled</span>
            <span className="v">{s.scheduled}</span>
          </div>
          <div>
            <span className="label">Posted</span>
            <span className="v">{s.posted}</span>
          </div>
          <div>
            <span className="label">Views</span>
            <span className="v">{formatViews(s.views)}</span>
          </div>
          <div>
            <span className="label">Best ×</span>
            <span className="v">
              <OutlierBadge x={s.bestX} />
            </span>
          </div>
          <div>
            <span className="label">Credits, month</span>
            <span className="v">{formatCredits(s.creditsMonth)}</span>
          </div>
        </div>
      </div>
      <VideoGroup id="artist-videos-live" title="Live" rows={g.live.slice(0, POSTED_SHOWN)} total={g.live.length} name={name} empty={`${name} has nothing posted yet.`} />
      <VideoGroup id="artist-videos-scheduled" title="Scheduled" rows={g.scheduled} total={g.scheduled.length} name={name} empty="Nothing is booked to go out." />
      <VideoGroup
        id="artist-videos-making"
        title="In the making"
        rows={g.making}
        total={g.making.length}
        name={name}
        empty={<>Nothing is being made: drop a clip in <a href={href('clips')}>Clips</a>.</>}
      />
      {g.live.length > POSTED_SHOWN && (
        <a className="small stage-more" href={all}>
          Showing {POSTED_SHOWN} of {g.live.length} posted · all his videos
        </a>
      )}
    </Section>
  );
}
