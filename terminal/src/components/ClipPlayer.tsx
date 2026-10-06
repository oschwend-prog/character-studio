// The video of a finished clip (its master in Storage, played through a short-lived signed URL): the Queue and the
// Library both use it. Without a master, or in demo mode, a stand-in frame shows the hook.
import { useEffect, useState } from 'react';
import { clipCode } from '../lib/format';
import { useStudio } from '../lib/store';

export interface PlayableClip {
  id: string;
  character_slug: string;
  hook: string | null;
  master_path: string | null;
}

export function ClipPlayer({ clip, demo }: { clip: PlayableClip; demo: boolean }) {
  const { backend } = useStudio();
  const [src, setSrc] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'none'>('loading');
  useEffect(() => {
    let live = true;
    if (!clip.master_path) {
      setState('none');
      return;
    }
    backend.signedUrl(clip.master_path).then((u) => {
      if (!live) return;
      setSrc(u);
      setState(u ? 'ready' : 'none');
    });
    return () => {
      live = false;
    };
  }, [backend, clip.master_path]);

  return (
    <div className="player">
      {state === 'ready' && src ? (
        <video src={src} controls playsInline loop preload="metadata" aria-label={`Clip ${clipCode(clip.id, clip.character_slug)}: ${clip.hook ?? ''}`} />
      ) : (
        <div className={`stand-in ${clip.character_slug}`} role="img" aria-label={demo ? 'Demo stand-in frame: no video in demo mode' : 'No playable master'}>
          <span className="top">
            <span className="note">{state === 'loading' ? 'Loading master…' : demo ? 'Demo stand-in · no video' : 'No master file to play'}</span>
            <span className="bug" aria-hidden="true">
              <i />
              <i />
            </span>
          </span>
          <span className="hookline">{clip.hook}</span>
          <span />
        </div>
      )}
    </div>
  );
}


