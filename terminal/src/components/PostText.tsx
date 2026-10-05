// The exact text a post goes out with (caption + the AI disclosure line + hashtags, composed like studio.captions does) and the
// first comment the owner pins, each with a Copy button. The clipboard when the browser allows it, else the text is selected and
// the owner copies it ("Select and copy"); a short "Copied" says it worked.
import { Check, Copy } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { copyText, postText } from '../lib/captions';

export function PostText({ caption, hashtags, firstComment }: { caption: string | null | undefined; hashtags: ReadonlyArray<string> | null | undefined; firstComment: string | null | undefined }) {
  const composed = postText(caption, hashtags);
  return (
    <div className="post-text">
      <CopyBlock label="Post text" text={composed.text} error={composed.error} />
      {firstComment ? (
        <CopyBlock label="First comment · pin it" text={firstComment} />
      ) : (
        <p className="small muted" style={{ margin: 0 }}>No first comment yet: the daily run writes one with the caption.</p>
      )}
    </div>
  );
}

function CopyBlock({ label, text, error }: { label: string; text: string | null; error?: string | null }) {
  const id = useId();
  const box = useRef<HTMLTextAreaElement>(null);
  const [state, setState] = useState<'idle' | 'copied' | 'select'>('idle');
  useEffect(() => setState('idle'), [text]);
  useEffect(() => {
    if (state !== 'copied') return;
    const t = window.setTimeout(() => setState('idle'), 2000);
    return () => window.clearTimeout(t);
  }, [state]);

  const copy = async () => {
    if (!text) return;
    const how = await copyText(text, typeof navigator === 'undefined' ? null : navigator.clipboard);
    if (how === 'select' && box.current) {
      box.current.focus();
      box.current.select();
      box.current.setSelectionRange(0, text.length); // iOS selects only through the range
    }
    setState(how);
  };

  return (
    <div className="copy-block">
      <div className="copy-head">
        <label className="label" htmlFor={id}>
          {label}
        </label>
        <button type="button" className="btn ghost copy-btn" onClick={() => void copy()} disabled={!text} aria-label={`Copy the ${label.split(' ·')[0].toLowerCase()}`}>
          {state === 'copied' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {state === 'copied' ? 'Copied' : 'Copy'}
        </button>
      </div>
      {text ? (
        <textarea id={id} ref={box} className="textarea copy-text" readOnly value={text} rows={rowsFor(text)} />
      ) : (
        <p className="error-text" style={{ margin: 0 }}>
          It would be refused: {error}
        </p>
      )}
      <span className={state === 'select' ? 'hint' : 'sr-only'} role="status" aria-live="polite">
        {state === 'select' ? 'Select and copy: the text is selected, use Copy from your phone’s menu.' : state === 'copied' ? 'Copied' : ''}
      </span>
    </div>
  );
}

/** Rows enough to show the whole text on a phone (about 38 characters a row) without an inner scroll, 16 at most. */
function rowsFor(text: string): number {
  const rows = text.split('\n').reduce((n, line) => n + Math.max(1, Math.ceil([...line].length / 38)), 0);
  return Math.min(16, rows);
}
