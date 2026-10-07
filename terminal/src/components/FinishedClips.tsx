// "Finished clips" (owner 2026-10-06), on Characters > All videos under the list: every made clip, waiting for his OK, approved,
// scheduled or posted, with the Queue's player (ClipPlayer: the master through a short-lived signed URL), its character and where
// it is. Approving stays in Videos (To approve): a clip waiting for his OK links there. The newest first; the first FINISHED_PAGE,
// then "Show all".
import { ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { FINISHED_LABEL, FINISHED_PAGE, FINISHED_TONE, type FinishedState } from '../lib/finished';
import { clipCode, formatViews, londonStamp } from '../lib/format';
import { href } from '../lib/hooks';
import { useStudio } from '../lib/store';
import type { LibraryClip } from '../lib/types';
import { ClipPlayer } from './ClipPlayer';
import { Livery } from './ui';

export function FinishedClips({ clips }: { clips: ReadonlyArray<LibraryClip> }) {
  const { backend } = useStudio();
  const [all, setAll] = useState(false);
  const shown = all ? clips : clips.slice(0, FINISHED_PAGE);
  const waiting = clips.filter((c) => c.state === 'awaiting_approval').length;
  return (
    <section className="stack" style={{ gap: 10 }} aria-labelledby="finished-title">
      <div>
        <h2 className="h2" id="finished-title">Finished clips</h2>
        <p className="small muted num" style={{ margin: '6px 0 0' }}>
          {clips.length === 0
            ? 'Nothing made yet: a clip shows here once it is built.'
            : `${clips.length} made${waiting ? ` · ${waiting} waiting for your OK in Videos` : ''}`}
        </p>
      </div>
      {clips.length > 0 && (
        <div className="finished-grid">
          {shown.map((c) => (
            <Finished key={c.id} clip={c} demo={backend.kind === 'demo'} />
          ))}
        </div>
      )}
      {!all && clips.length > FINISHED_PAGE && (
        <button type="button" className="btn line" style={{ alignSelf: 'flex-start' }} onClick={() => setAll(true)}>
          Show all {clips.length} clips
        </button>
      )}
    </section>
  );
}

function Finished({ clip: c, demo }: { clip: LibraryClip; demo: boolean }) {
  const state = c.state as FinishedState;
  const post = c.posts.find((p) => p.status === 'posted' && p.url && /^https:/.test(p.url));
  const titleId = `finished-${c.id}`;
  return (
    <article className="panel pick" data-char={c.character_slug} aria-labelledby={titleId}>
      <div className="pick-badges">
        <span className={`tag ${FINISHED_TONE[state]}`}>{FINISHED_LABEL[state]}</span>
        <Livery slug={c.character_slug} />
        <span className="small muted num">{clipCode(c.id, c.character_slug)}</span>
      </div>
      <h3 className="work-title" id={titleId}>{c.hook ? `“${c.hook}”` : clipCode(c.id, c.character_slug)}</h3>
      <ClipPlayer clip={c} demo={demo} />
      <p className="pick-meta" style={{ margin: 0 }}>
        <span className="num">{londonStamp(c.posted_at ?? c.created_at)}</span>
        {c.views != null && <span className="num">{formatViews(c.views)} views</span>}
      </p>
      {(state === 'awaiting_approval' || post) && (
        <div className="work-links">
          {state === 'awaiting_approval' && (
            <a className="btn primary" href={href('videos', c.id)}>
              Review in Videos
            </a>
          )}
          {post && (
            <a className="btn ghost" href={post.url!} target="_blank" rel="noopener noreferrer">
              View post <ExternalLink aria-hidden="true" />
            </a>
          )}
        </div>
      )}
    </article>
  );
}
