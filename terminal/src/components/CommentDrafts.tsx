// Today's "Comments to post today" (owner 2026-10-28): the comments the daily run drafted for the owner to post BY HAND, from each
// character's own Instagram account, on big accounts in his niche (about 5 each, about 10 minutes). The studio never posts one itself.
// Per character: @handle, Open post (a new tab), the comment, and a Copy button (the clipboard when the browser allows it, else the text
// is selected for the owner to copy; a short "Copied" says it worked). The card is hidden when there are no drafts today. It is built
// from the neighbouring "Last posts" card's own parts (Section, panel rows, pipe rows, btn line): nothing new in styles.css.
import { Check, Copy, ExternalLink } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { copyText } from '../lib/captions';
import { draftsForDay, groupDrafts, type CommentDraft, type CommentGroup } from '../lib/comments';
import { londonDayKey } from '../lib/format';
import { useStudio } from '../lib/store';
import { Livery, Section } from './ui';

/** What Copy does for one draft: the comment goes to the clipboard (`copied`), or the page must select it (`select`). */
export const copyDraft = (draft: Pick<CommentDraft, 'comment'>, clipboard: Pick<Clipboard, 'writeText'> | null | undefined) =>
  copyText(draft.comment, clipboard);

export function CommentDrafts({ now }: { now: number }) {
  const { data } = useStudio();
  const day = londonDayKey(now);
  const groups = useMemo(() => (data ? groupDrafts(draftsForDay(data.commentDrafts, day), data.characters) : []), [data, day]);
  if (groups.length === 0) return null;
  return <CommentsCard groups={groups} />;
}

export function CommentsCard({ groups }: { groups: ReadonlyArray<CommentGroup> }) {
  const total = groups.reduce((n, g) => n + g.drafts.length, 0);
  if (total === 0) return null;
  return (
    <Section id="comments" title="Comments to post today" aside={<span className="num">{total}</span>}>
      <p className="small muted" style={{ margin: 0 }}>
        Drafted in each character’s voice. Open the post, copy the comment and post it yourself from his account.
      </p>
      <div className="panel rows">
        {groups.map((g) => (
          <div key={g.slug} className="panel-pad">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Livery slug={g.slug} />
              <b style={{ fontSize: 14 }}>{g.name}</b>
            </div>
            <ul className="pipe-list" aria-label={`${g.name}’s comments to post`}>
              {g.drafts.map((d) => (
                <CommentRow key={`${d.character}|${d.handle}`} draft={d} />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Section>
  );
}

function CommentRow({ draft }: { draft: CommentDraft }) {
  const text = useRef<HTMLElement>(null);
  const [state, setState] = useState<'idle' | 'copied' | 'select'>('idle');
  useEffect(() => setState('idle'), [draft.comment]);
  useEffect(() => {
    if (state !== 'copied') return;
    const t = window.setTimeout(() => setState('idle'), 2000);
    return () => window.clearTimeout(t);
  }, [state]);

  const copy = async () => {
    const how = await copyDraft(draft, typeof navigator === 'undefined' ? null : navigator.clipboard);
    if (how === 'select' && text.current) selectContents(text.current);
    setState(how);
  };

  return (
    <li className="pipe-row" data-char={draft.character}>
      <div className="pipe-main">
        <div className="pipe-meta">
          <span>{draft.handle}</span>
          <a className="link" href={draft.postUrl} target="_blank" rel="noopener noreferrer" aria-label={`Open ${draft.handle}’s post (a new tab)`}>
            Open post <ExternalLink size={12} aria-hidden="true" />
          </a>
        </div>
        <b className="pipe-hook" ref={text}>
          {draft.comment}
        </b>
        <span className={state === 'select' ? 'hint' : 'sr-only'} role="status" aria-live="polite">
          {state === 'select' ? 'Select and copy: the text is selected, use Copy from your phone’s menu.' : state === 'copied' ? 'Copied' : ''}
        </span>
      </div>
      <button type="button" className="btn line" onClick={() => void copy()} aria-label={`Copy the comment for ${draft.handle}`}>
        {state === 'copied' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        {state === 'copied' ? 'Copied' : 'Copy'}
      </button>
    </li>
  );
}

/** The clipboard was not allowed: select the comment so the owner can copy it from the phone's menu (iOS selects only through a range). */
function selectContents(el: Element) {
  const sel = window.getSelection();
  if (!sel) return;
  const range = document.createRange();
  range.selectNodeContents(el);
  sel.removeAllRanges();
  sel.addRange(range);
}
