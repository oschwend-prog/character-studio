// The board's parts: split-flap text, the two-dot mark, liveries, switches, badges, meters.
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { autopilotState, tabIndexAfter } from '../lib/rules';
import { outlierBadge, platformName } from '../lib/format';

const DRUM = ' ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:-.';
const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/**
 * Split-flap text. When the value changes, each changed cell steps through the drum a few glyphs
 * before landing (the signature move: Realtime changes flip on the board). Screen readers get the
 * plain text once.
 */
export function Flap({
  text, size, tone, cells, label,
}: { text: string; size?: 'big' | 'mid'; tone?: string; cells?: number; label?: string }) {
  const target = text.toUpperCase().padEnd(cells ?? 0, ' ');
  const [shown, setShown] = useState(target);
  const prev = useRef(target);

  useEffect(() => {
    const from = prev.current;
    if (from === target) return;
    prev.current = target;
    if (reducedMotion()) {
      setShown(target);
      return;
    }
    const steps = 5;
    let step = 0;
    const width = Math.max(from.length, target.length);
    const id = window.setInterval(() => {
      step += 1;
      if (step >= steps) {
        window.clearInterval(id);
        setShown(target);
        return;
      }
      let out = '';
      for (let i = 0; i < width; i++) {
        const want = target[i] ?? ' ';
        if ((from[i] ?? ' ') === want) {
          out += want;
          continue;
        }
        const at = DRUM.indexOf(want);
        out += at < 0 ? want : DRUM[(at - (steps - step) * 3 + DRUM.length * 4) % DRUM.length];
      }
      setShown(out);
    }, 60);
    return () => window.clearInterval(id);
  }, [target]);

  return (
    <span className={['flap', size, tone && `tone-${tone}`].filter(Boolean).join(' ')}>
      {Array.from(shown).map((ch, i) => (
        <span
          key={i}
          aria-hidden="true"
          className={`flap-cell${ch === ' ' ? ' space' : ''}${ch !== (target[i] ?? ' ') ? ' turning' : ''}`}
        >
          {ch === ' ' ? ' ' : ch}
        </span>
      ))}
      <span className="sr-only">{label ?? text}</span>
    </span>
  );
}

/** The ODD EYES two-dot mark; the dots are lit while live updates are connected. */
export function Mark({ on = true, label }: { on?: boolean; label?: string }) {
  return (
    <span className="mark" data-state={on ? 'on' : 'off'} role="img" aria-label={label ?? 'ODD EYES'}>
      <i />
      <i />
    </span>
  );
}

const LIVERY: Record<string, string> = { biscuit: 'BSC', reginald: 'RGN' };
const NAME: Record<string, string> = { biscuit: 'Biscuit', reginald: 'Reginald' };

export function Livery({ slug }: { slug: string | null }) {
  if (!slug) {
    return (
      <span className="livery none" title="No character yet">
        <span aria-hidden="true">—</span>
        <span className="sr-only">No character yet</span>
      </span>
    );
  }
  return (
    <span className={`livery ${slug in LIVERY ? slug : 'none'}`} title={NAME[slug] ?? slug}>
      <span aria-hidden="true">{LIVERY[slug] ?? slug.slice(0, 3).toUpperCase()}</span>
      <span className="sr-only">{NAME[slug] ?? slug}</span>
    </span>
  );
}

export const characterName = (slug: string | null) => (slug ? NAME[slug] ?? slug : 'Unassigned');

export function OutlierBadge({ x }: { x: number | null | undefined }) {
  const b = outlierBadge(x);
  const words = { hit: 'hit', good: 'good', neutral: '', weak: 'weak', none: 'no result yet' }[b.tone];
  return (
    <span className={`tag ox ${b.tone}`} title={`outlier ${b.label}${words ? ` (${words})` : ''}`}>
      {b.label}
      {b.tone === 'hit' && <span aria-hidden="true">HIT</span>}
      <span className="sr-only">{words ? `, ${words}` : ''}</span>
    </span>
  );
}

export function PlatformCode({ platform }: { platform: string }) {
  const code = platform === 'tiktok' ? 'TT' : platform === 'instagram' ? 'IG' : platform === 'youtube' ? 'YT' : '??';
  return <Flap text={code} label={platformName(platform)} />;
}

/** Posting autopilot for one channel, with the lock rule spelled out. */
export function AutopilotSwitch({
  channel, busy, onToggle, compact, allConnectedAuto,
}: {
  channel: { account_id: string; character_slug: string; handle: string | null; platform: string; mode: string; approved_posts: number | null };
  busy: boolean;
  onToggle(next: 'auto' | 'approval'): void;
  compact?: boolean;
  /** Every connected account of this character is on autopilot (only then does posting skip the queue). */
  allConnectedAuto?: boolean;
}) {
  const s = autopilotState(channel, { characterName: characterName(channel.character_slug), allConnectedAuto });
  const id = `ap-${channel.account_id}`;
  const approved = Math.min(channel.approved_posts ?? 0, 6);
  return (
    <div className="auto-row">
      <div className="txt">
        <b id={`${id}-l`}>{compact ? `${platformName(channel.platform)}` : 'Posting autopilot'}</b>
        <span className="small muted" id={`${id}-d`}>
          {s.reason}
        </span>
        {s.locked && (
          <span className="lock-progress" aria-hidden="true">
            {Array.from({ length: 6 }, (_, i) => (
              <span key={i} className={i < approved ? 'on' : ''} />
            ))}
          </span>
        )}
      </div>
      <span className="switch-hit">
        <button
          type="button"
          role="switch"
          className="switch"
          aria-checked={s.on}
          aria-describedby={`${id}-d`}
          aria-label={`Posting autopilot for ${channel.handle ?? platformName(channel.platform)}`}
          disabled={!s.canToggle || busy}
          aria-busy={busy}
          onClick={() => onToggle(s.on ? 'approval' : 'auto')}
        />
      </span>
    </div>
  );
}

export function Section({ title, aside, children, id }: { title: ReactNode; aside?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className="section" aria-labelledby={id}>
      <div className="section-head">
        <h2 className="h2" id={id}>
          {title}
        </h2>
        {aside && <div className="aside">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

export function Spinner() {
  return <span className="spin" aria-hidden="true" />;
}

export function Skeleton({ h = 56 }: { h?: number }) {
  return <div className="skeleton" style={{ height: h }} aria-hidden="true" />;
}

/** A character's picture (terminal/public/avatars/<slug>.png); an unknown slug, or a picture that fails, shows initials. */
export function Avatar({ slug, name, size = 48 }: { slug: string; name?: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  const label = name ?? characterName(slug);
  const initials = label
    .split(/\s+/)
    .map((w) => w.charAt(0))
    .join('')
    .slice(0, 2)
    .toUpperCase();
  const style = { width: size, height: size, fontSize: Math.round(size * 0.38) };
  if (broken)
    return (
      <span className={`avatar initials ${slug in LIVERY ? slug : 'none'}`} style={style} aria-hidden="true">
        {initials}
      </span>
    );
  return (
    <img
      className="avatar"
      src={`/avatars/${encodeURIComponent(slug)}.png`}
      alt=""
      width={size}
      height={size}
      style={style}
      onError={() => setBroken(true)}
    />
  );
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * A modal sheet (bottom sheet on a phone, centred from tablet width): labelled by its title, Escape and a tap on
 * the backdrop close it, Tab stays inside, the page behind is inert and does not scroll, and focus goes back to
 * what opened it. Content is rendered in a portal so no page layout can clip it.
 */
export function Sheet({ title, onClose, children }: { title: ReactNode; onClose(): void; children: ReactNode }) {
  const titleId = useId();
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const root = document.getElementById('root');
    root?.setAttribute('inert', '');
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const items = () => Array.from(box.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    (items().find((el) => el.getAttribute('aria-pressed') === 'true') ?? items()[0] ?? box.current)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close.current();
        return;
      }
      if (e.key !== 'Tab') return;
      const list = items();
      if (!list.length) return e.preventDefault();
      const at = list.indexOf(document.activeElement as HTMLElement);
      const next = tabIndexAfter(at, list.length, e.shiftKey);
      const wraps = at < 0 || (e.shiftKey ? at === 0 : at === list.length - 1);
      if (wraps) {
        e.preventDefault();
        list[next]?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      root?.removeAttribute('inert');
      document.body.style.overflow = overflow;
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);

  return createPortal(
    <div
      className="sheet-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div ref={box} className="sheet" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="sheet-head">
          <h2 className="h2" id={titleId}>
            {title}
          </h2>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
