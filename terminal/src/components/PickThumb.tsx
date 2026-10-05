// The picture on a pick: a 9:16 frame (16:9 pictures are letterboxed in it) showing the thumbnail a tool returned, or a
// tidy platform-colour tile when there is none or the image failed (platform CDN links expire). A video preview (a
// Genjutsu preset's) plays muted, looping and inline on tap, and pauses when it scrolls away. We never fetch or rehost
// anything: the browser loads the URL itself, without a referrer.
import { ExternalLink, Play } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { thumbFor } from '../lib/rules';

type ThumbPick = Parameters<typeof thumbFor>[0];

export function PickThumb({ pick, size = 'card' }: { pick: ThumbPick; size?: 'card' | 'small' }) {
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState(false);
  const spec = thumbFor(pick, { imageFailed: failed });
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    setFailed(false);
    setPlaying(false);
  }, [pick.thumbnail_url, pick.preview_url]);

  // pause a playing preview when it scrolls out of view (and let it resume when it is back)
  useEffect(() => {
    const el = video.current;
    if (!playing || !el || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) el.pause();
      else void el.play().catch(() => undefined);
    }, { threshold: 0.25 });
    io.observe(el);
    return () => io.disconnect();
  }, [playing]);

  const cls = `thumb ${size} ${spec.aspect === '16:9' ? 'wide' : 'tall'}`;

  if (playing && spec.preview) {
    return (
      <div className={cls}>
        <button type="button" className="thumb-hit" onClick={() => setPlaying(false)} aria-label={`Stop the preview of ${pick.hook ?? 'this video'}`}>
          <video ref={video} src={spec.preview} muted loop playsInline autoPlay preload="metadata" aria-label={`Preview of ${pick.hook ?? 'this video'}`} />
        </button>
      </div>
    );
  }

  const picture =
    spec.kind === 'image' ? (
      <img src={spec.src!} alt={spec.alt} loading="lazy" referrerPolicy="no-referrer" decoding="async" onError={() => setFailed(true)} />
    ) : (
      <span className={`thumb-tile plat-${spec.platform}`} role="img" aria-label={spec.alt}>
        <b className="mono">{spec.code}</b>
        {size === 'card' && spec.handle && <span className="who">{spec.handle}</span>}
        {size === 'card' && spec.original && (
          <a className="orig" href={spec.original} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
            View original <ExternalLink size={12} aria-hidden="true" />
          </a>
        )}
      </span>
    );

  if (spec.preview) {
    return (
      <div className={cls}>
        <button type="button" className="thumb-hit" onClick={() => setPlaying(true)} aria-label={`Play the preview of ${pick.hook ?? 'this video'}`}>
          {picture}
          <span className="play" aria-hidden="true">
            <Play size={size === 'small' ? 12 : 18} />
          </span>
        </button>
      </div>
    );
  }
  return <div className={cls}>{picture}</div>;
}
