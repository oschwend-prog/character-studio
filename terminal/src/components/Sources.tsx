// Sources, the top of New clips (owner 2026-10-15: "we should be able to see source of clips on top - we have the folder plus social
// media scan"): where the clips come from, one row each. The iCloud clips folder (studio drop sync-folder on the Mac, every 5 min:
// when its newest clip came, how many this week), a link or videos he adds here (DropBox), and the daily social scan (the cloud
// hits job: a closed fold with Hot right now and each live character's Worth saving; Use one and it joins the available clips,
// checked for free). Nothing here costs credits.
import { Flame, FolderOpen } from 'lucide-react';
import { formatAge } from '../lib/format';
import { hotNow, worthSaving } from '../lib/hits';
import { folderStatus } from '../lib/newclips';
import { useStudio } from '../lib/store';
import type { TrackerRow } from '../lib/types';
import { DropBox } from './DropBox';
import { HotRightNow, WorthSaving } from './Hits';

export function Sources({ rows, characters, now }: {
  rows: ReadonlyArray<TrackerRow>;
  /** The live characters: one Worth saving fold each. */
  characters: ReadonlyArray<{ slug: string; name: string }>;
  now: number;
}) {
  const { data } = useStudio();
  const folder = folderStatus(rows, now);
  const hits = data?.hits ?? [];
  const hot = hotNow(hits).length;
  const theirs = characters.reduce((n, c) => n + worthSaving(hits, c.slug).length, 0);
  return (
    <section className="panel sources" aria-labelledby="sources-title">
      <h2 className="h2" id="sources-title">Sources</h2>
      <div className="source-row">
        <h3 className="source-title"><FolderOpen size={16} aria-hidden="true" /> Clips folder</h3>
        <p className="small muted" style={{ margin: 0 }}>
          {folder.newest ? `Newest ${formatAge(folder.newest, now)} · ${folder.week} this week. ` : 'Nothing from it yet. '}
          Save a video to iCloud Drive › ODD EYES clips: it shows up here within 5 minutes.
        </p>
      </div>
      <DropBox embedded />
      <details className="source-row scan">
        <summary>
          <h3 className="source-title"><Flame size={16} aria-hidden="true" /> Social scan</h3>
          <span className="small muted">{hot} hot now · {theirs} for your characters · new every morning</span>
        </summary>
        <div className="stack scan-body">
          <HotRightNow now={now} />
          {characters.map((c) => <WorthSaving key={c.slug} slug={c.slug} name={c.name} now={now} />)}
        </div>
      </details>
    </section>
  );
}
