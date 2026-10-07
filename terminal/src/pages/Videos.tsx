// Videos (terminal v2, owner 2026-10-07): everything after Make it, in three groups in the order a video travels. Making: the
// picks on their 8 steps (cards, grouped by character) and the clips being built; To approve: the Queue (watch it, edit the hook
// and caption, Approve or Reject); Scheduled: when and where each approved video goes out. A posted video moves on to its
// character (Characters, All videos). `focus` is a clip id (`#/videos/<id>`): the Queue opens on it.
import { useEffect } from 'react';
import { WorkCards } from '../components/WorkCards';
import { Livery, Section, Skeleton } from '../components/ui';
import { formatAge, formatCredits, londonStamp, platformName } from '../lib/format';
import { href, useNow } from '../lib/hooks';
import { useStudio } from '../lib/store';
import type { LibraryClip } from '../lib/types';
import { clipPlatforms, isTrackerRow, slotTime, videoGroups } from '../lib/videos';
import { Queue } from './Queue';

const FAILED_STATES: ReadonlyArray<string> = ['gen_failed', 'qa_failed'];
/** The sticky top bar's height, kept clear when a link scrolls to the Queue. */
const TOPBAR = 64;

export function Videos({ focus }: { focus: string | null }) {
  const { data } = useStudio();
  const now = useNow(60_000);
  const loaded = data != null;
  // a link to one clip (Today, the tracker card, an old bookmark) lands on the Queue, below Making
  useEffect(() => {
    if (!focus || !loaded) return;
    const el = document.getElementById('videos-approve');
    if (el) window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - TOPBAR) });
  }, [focus, loaded]);

  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={90} />
        <Skeleton h={300} />
      </div>
    );
  }
  const { making, scheduled } = videoGroups(data);
  const rows = making.filter(isTrackerRow);
  const clips = making.filter((x): x is LibraryClip => !isTrackerRow(x));
  return (
    <div className="page stack">
      <div>
        <h1 className="h1">Videos</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          Everything after Make it: what is being made, what waits for your OK, and what is booked to go out. A posted video moves to its
          character.
        </p>
      </div>

      <Section id="videos-making" title="Making" aside={making.length ? <span className="num">{making.length}</span> : undefined}>
        {making.length === 0 && (
          <p className="small muted" style={{ margin: 0 }}>
            Nothing is being made right now. Pick a character for a clip and Make it in <a href={href('clips')}>Clips</a>.
          </p>
        )}
        <WorkCards rows={rows} now={now} />
        {clips.length > 0 && (
          <ul className="pipe-list" aria-label="Clips being built">
            {clips.map((c) => (
              <li key={c.id} className="pipe-row">
                <div className="pipe-main">
                  <b className="pipe-hook">{c.hook ? `“${c.hook}”` : 'untitled clip'}</b>
                  <div className="pipe-meta">
                    <Livery slug={c.character_slug} />
                    <span className={`tag${FAILED_STATES.includes(c.state) ? ' alert' : ' action'}`}>{c.state.replace('_', ' ')}</span>
                    <span>{formatAge(c.created_at, now)}</span>
                    <span className="num">{formatCredits(c.cost_credits)}</span>
                  </div>
                </div>
                <a className="btn line" href={href('characters', 'all', { clip: c.id })} aria-label={`Open ${c.hook ?? 'this clip'} in All videos`}>
                  Open
                </a>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="videos-approve" title="To approve" aside={<span className="num">{data.queue.length}</span>}>
        <Queue focus={focus} embedded />
      </Section>

      <Section id="videos-scheduled" title="Scheduled" aside={scheduled.length ? <span className="num">{scheduled.length}</span> : undefined}>
        {scheduled.length === 0 ? (
          <p className="small muted" style={{ margin: 0 }}>Nothing is booked yet: an approved video gets its slot here.</p>
        ) : (
          <ul className="pipe-list" aria-label="Scheduled videos">
            {scheduled.map((c) => {
              const at = slotTime(c);
              const where = clipPlatforms(c);
              return (
                <li key={c.id} className="pipe-row">
                  <div className="pipe-main">
                    <b className="pipe-hook">{c.hook ? `“${c.hook}”` : 'untitled clip'}</b>
                    <div className="pipe-meta">
                      <Livery slug={c.character_slug} />
                      <span className={`tag${c.state === 'scheduled' ? ' live' : ''}`}>{c.state === 'approved' ? 'approved' : 'scheduled'}</span>
                      <span className="num">{at ? londonStamp(at) : 'no slot yet'}</span>
                      {where.length > 0 && <span>{where.map(platformName).join(' + ')}</span>}
                    </div>
                  </div>
                  <a className="btn line" href={href('characters', 'all', { clip: c.id })} aria-label={`Open ${c.hook ?? 'this clip'} in All videos`}>
                    Open
                  </a>
                </li>
              );
            })}
          </ul>
        )}
      </Section>
    </div>
  );
}
