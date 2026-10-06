// "Drop a video" (plan 2026-10-06): the box at the top of "In the works". Pick one or more videos from the phone (or paste a link):
// each becomes a row of the drops table that moves by itself (Uploading → Checking → Ready). The character is "Recommend" by
// default (owner 2026-10-06: the studio recommends one after the free check and files the drop under him); the owner can still
// pick one (never paused) and that choice is never overridden. Files go one after another, each straight to our own storage
// (sources/owner/<pick id>/), then the free check is asked for. Nothing is generated here: only the row's Make it does that.
import { Link2, Upload } from 'lucide-react';
import { useId, useMemo, useState, type ChangeEvent, type FormEvent } from 'react';
import { DROP_HELP, RECOMMEND, dropLink, type UploadPhase } from '../lib/drop';
import { validateClipFile } from '../lib/rules';
import { activeRoster } from '../lib/roster';
import { useStudio } from '../lib/store';
import { Spinner } from './ui';

interface Upload {
  id: number;
  name: string;
  state: UploadPhase;
}

/** The length of a video the browser can read (null when it cannot): checked before anything is uploaded. */
function readDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const v = document.createElement('video');
    let timer = 0;
    const done = (d: number | null) => {
      window.clearTimeout(timer);
      URL.revokeObjectURL(url);
      v.removeAttribute('src');
      resolve(d);
    };
    timer = window.setTimeout(() => done(null), 10_000);
    v.preload = 'metadata';
    v.muted = true;
    v.onloadedmetadata = () => done(Number.isFinite(v.duration) ? v.duration : null);
    v.onerror = () => done(null);
    v.src = url;
  });
}

export function DropBox() {
  const { backend, data, run, refresh, toast } = useStudio();
  const ids = useId();
  const roster = useMemo(() => activeRoster(data?.characters), [data?.characters]);
  // "Recommend" every time the page opens (not remembered): a character picked once must not stick to the next drops
  const [character, setCharacter] = useState<string>(RECOMMEND);
  const chosen = character === RECOMMEND || roster.some((c) => c.slug === character) ? character : RECOMMEND;
  const slugFor = () => (chosen === RECOMMEND ? null : chosen);
  const [link, setLink] = useState('');
  const [linkError, setLinkError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const busy = uploads.some((u) => u.state.phase === 'reading' || u.state.phase === 'uploading');

  const set = (id: number, state: UploadPhase) => setUploads((list) => list.map((u) => (u.id === id ? { ...u, state } : u)));

  const onFiles = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ''; // the same files can be chosen again
    if (!files.length) return;
    const base = Date.now();
    const rows = files.map((f, i) => ({ id: base + i, name: f.name, state: { phase: 'reading' } as UploadPhase }));
    setUploads((list) => [...list.filter((u) => u.state.phase !== 'done'), ...rows]);
    const slug = slugFor();
    let filed = 0;
    for (const [i, file] of files.entries()) {
      // one after another: a phone uploads one big file faster than four at once, and every card appears as soon as it is filed
      const id = rows[i].id;
      const checked = validateClipFile(file, await readDuration(file));
      if (!checked.ok) {
        set(id, { phase: 'error', message: checked.reason });
        continue;
      }
      try {
        set(id, { phase: 'uploading', pct: 0 });
        const { pickId } = await backend.addDrop(slug, null);
        void refresh(); // the card appears at Uploading
        await backend.attachClip(pickId, { name: file.name, size: file.size, type: file.type, blob: file }, (pct) => set(id, { phase: 'uploading', pct }));
        await backend.requestJob(pickId, 'process');
        set(id, { phase: 'done' });
        filed += 1;
      } catch (err) {
        set(id, { phase: 'error', message: err instanceof Error ? err.message : String(err) });
      }
    }
    void refresh();
    if (filed) toast(filed === 1 ? 'Dropped: it is being checked' : `${filed} videos dropped: they are being checked`);
  };

  const onLink = async (e: FormEvent) => {
    e.preventDefault();
    const parsed = dropLink(link);
    if (!parsed.ok) {
      setLinkError(parsed.reason);
      return;
    }
    const ok = await run('drop-link', async () => {
      const { pickId, duplicate } = await backend.addDrop(slugFor(), parsed.url);
      // a link that is already on its way (queued or made) needs no new check: that refusal is not an error
      await backend.requestJob(pickId, 'process').catch((err) => {
        if (!duplicate) throw err;
      });
    }, 'Link dropped: it is being checked');
    if (ok) setLink('');
  };

  const shown = uploads.filter((u) => u.state.phase !== 'done' || busy);
  return (
    <section className="panel drop-box" aria-labelledby={`${ids}-title`}>
      <div className="drop-head">
        <h2 className="h2" id={`${ids}-title`}>Drop a video</h2>
        <div className="seg" role="group" aria-label="For which character">
          <button type="button" aria-pressed={chosen === RECOMMEND} onClick={() => setCharacter(RECOMMEND)} title="The studio picks the character after the free check">
            ★ Recommend
          </button>
          {roster.map((c) => (
            <button key={c.slug} type="button" className={c.slug} aria-pressed={chosen === c.slug} onClick={() => setCharacter(c.slug)}>
              {c.name}
            </button>
          ))}
        </div>
      </div>
      <label className={`btn primary block drop-pick${busy ? ' disabled' : ''}`}>
        <Upload aria-hidden="true" /> Choose videos
        <input type="file" accept="video/*" multiple className="sr-only" onChange={onFiles} disabled={busy} aria-describedby={`${ids}-help`} />
      </label>
      <form className="drop-link" onSubmit={onLink}>
        <label className="sr-only" htmlFor={`${ids}-link`}>Or paste a link</label>
        <Link2 aria-hidden="true" className="drop-link-icon" />
        <input
          id={`${ids}-link`} className="input" inputMode="url" autoComplete="off" placeholder="Or paste a TikTok, Instagram or YouTube link"
          value={link} aria-invalid={linkError ? true : undefined} aria-describedby={linkError ? `${ids}-link-error` : undefined}
          onChange={(e) => {
            setLink(e.target.value);
            setLinkError(null);
          }}
        />
        <button type="submit" className="btn line" disabled={!link.trim()}>
          Add
        </button>
      </form>
      {linkError && (
        <span className="error-text" id={`${ids}-link-error`} role="alert">
          {linkError}
        </span>
      )}
      <p className="hint" id={`${ids}-help`} style={{ margin: 0 }}>{DROP_HELP}</p>
      {shown.length > 0 && (
        <ul className="drop-uploads" aria-label="Uploads">
          {shown.map((u) => (
            <li key={u.id} className={`drop-upload ${u.state.phase}`}>
              <span className="drop-upload-name">{u.name}</span>
              {u.state.phase === 'reading' && <span className="small muted" role="status"><Spinner /> Reading…</span>}
              {u.state.phase === 'uploading' && (
                <span className="small" role="status">
                  <progress max={100} value={u.state.pct} aria-label={`Upload of ${u.name}`} /> {u.state.pct}%
                </span>
              )}
              {u.state.phase === 'done' && <span className="small ok-text">Uploaded</span>}
              {u.state.phase === 'error' && (
                <span className="error-text" role="alert">
                  {u.state.message}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
