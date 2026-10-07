// Characters (terminal v2, owner 2026-10-07): a card for each character (picture, status, handles, next slot) that opens his page
// (#/artist/<slug>: his profile, all his videos grouped Live, Scheduled and In the making, his results and autopilot). The switch
// "All videos" (#/characters/all) lists every video ever made (the old Library; `focus` is the clip to open, `?clip=`), then the
// finished clips with their players.
import { ChevronRight } from 'lucide-react';
import { FinishedClips } from '../components/FinishedClips';
import { ViewSwitch } from '../components/ViewSwitch';
import { Avatar, Livery, PlatformCode, Skeleton } from '../components/ui';
import { finishedClips } from '../lib/finished';
import { londonStamp, platformName } from '../lib/format';
import { href, useNow } from '../lib/hooks';
import { characterCards, type CharacterCard } from '../lib/roster';
import { useStudio } from '../lib/store';
import { CHARACTERS_VIEWS, type CharactersView } from '../lib/tabs';
import { Library } from './Library';

const STATUS_TAG: Record<string, string> = { live: 'live', designing: 'action', paused: '' };

export function Characters({ view, focus }: { view: CharactersView; focus: string | null }) {
  const { data } = useStudio();
  const now = useNow(60_000);
  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={90} />
        <Skeleton h={260} />
      </div>
    );
  }
  const cards = characterCards(data.characters, data.channels, now);
  return (
    <div className="page stack">
      <div>
        <h1 className="h1">Characters</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          Open a character for his videos, his results and his autopilot; “All videos” lists every one.
        </p>
      </div>
      <ViewSwitch
        label="Show"
        value={view}
        options={CHARACTERS_VIEWS}
        to={(id) => (id === 'all' ? href('characters', 'all') : href('characters'))}
      />
      {view === 'all' ? (
        <>
          <Library focus={focus} embedded />
          <FinishedClips clips={finishedClips(data.library)} />
        </>
      ) : cards.length === 0 ? (
        <div className="panel empty">
          <b>No characters yet</b>
          <span className="small muted">
            Run <code>bin/studio seed</code>: it reads <code>characters/&lt;slug&gt;/refs.json</code> and puts each character here, with its accounts as they get created.
          </span>
        </div>
      ) : (
        <div className="channels-grid stack" style={{ gap: 12 }}>
          {cards.map((c) => (
            <Card key={c.slug} card={c} />
          ))}
        </div>
      )}
    </div>
  );
}

function Card({ card: c }: { card: CharacterCard }) {
  const titleId = `char-${c.slug}`;
  return (
    <article className="panel panel-pad stack" style={{ gap: 12 }} aria-labelledby={titleId} data-char={c.slug}>
      <div className="char-head" style={{ paddingBottom: 0 }}>
        <a href={href('artist', c.slug)} aria-label={`${c.name}’s page`} tabIndex={-1}>
          <Avatar slug={c.slug} name={c.name} size={56} />
        </a>
        <div className="who">
          <h2 className="h1" id={titleId} style={{ fontSize: 22 }}>
            <a className="name-link" href={href('artist', c.slug)}>
              {c.name}
            </a>
          </h2>
          <span className="char-meta">
            <Livery slug={c.slug} />
            <span className={`tag ${STATUS_TAG[c.status] ?? ''}`}>{c.status}</span>
          </span>
        </div>
      </div>
      <div className="pipe-meta">
        {c.handles.length === 0 ? (
          <span className="muted">no handle yet</span>
        ) : (
          c.handles.map((h) => (
            <span key={h.platform} title={h.planned ? `${platformName(h.platform)}: planned, not created yet` : platformName(h.platform)}>
              <PlatformCode platform={h.platform} /> <span className={h.planned ? 'muted' : undefined}>{h.handle}</span>
            </span>
          ))
        )}
      </div>
      <div className="pipe-meta">
        <span className="label">Next slot</span>
        <span className="num">{c.nextSlot ? londonStamp(c.nextSlot) : '—'}</span>
      </div>
      <a className="link" href={href('artist', c.slug)}>
        His page <ChevronRight size={14} aria-hidden="true" />
      </a>
    </article>
  );
}
