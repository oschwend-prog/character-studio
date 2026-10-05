// Channels: one panel per social account with its results on the pre-registered yardsticks, its
// Drop-in share, and the posting autopilot switch with the lock rule.
import { Section, AutopilotSwitch, Livery, OutlierBadge, PlatformCode, Skeleton, characterName } from '../components/ui';
import { formatViews, londonStamp, platformName } from '../lib/format';
import { useStudio } from '../lib/store';
import type { Channel } from '../lib/types';

export function Channels() {
  const { data } = useStudio();
  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={260} />
      </div>
    );
  }
  const slugs = [...new Set(data.channels.map((c) => c.character_slug))];
  return (
    <div className="page stack">
      <div>
        <h1 className="h1">Channels</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          A hit is outlier 3× or more (views at 7 days against the channel’s own median). Autopilot unlocks after 6 approved posts.
        </p>
      </div>
      {data.channels.length === 0 && (
        <div className="panel empty">
          <b>No accounts yet</b>
          <span className="small muted">
            Create the TikTok and Instagram accounts, connect them in Postiz, put the handles and ids in <code>characters/&lt;slug&gt;/refs.json</code>, then run <code>bin/studio seed</code>.
          </span>
        </div>
      )}
      {slugs.map((slug) => (
        <Section key={slug} id={`ch-${slug}`} title={characterName(slug)} aside={<Livery slug={slug} />}>
          <div className="channels-grid stack" style={{ gap: 12 }}>
            {data.channels
              .filter((c) => c.character_slug === slug)
              .sort((a, b) => a.platform.localeCompare(b.platform))
              .map((c) => (
                <ChannelPanel
                  key={c.account_id}
                  channel={c}
                  allConnectedAuto={data.channels.filter((x) => x.character_slug === slug && x.connected).every((x) => x.mode === 'auto')}
                />
              ))}
          </div>
        </Section>
      ))}
    </div>
  );
}

function ChannelPanel({ channel: c, allConnectedAuto }: { channel: Channel; allConnectedAuto: boolean }) {
  const { backend, run, busy } = useStudio();
  const key = `mode-${c.account_id}`;
  const ratioPct = Math.round((c.dropin_ratio ?? 0) * 100);
  const sharePct = Math.round((c.dropin_share ?? 0) * 100);
  return (
    <article className="panel channel" aria-label={`${characterName(c.character_slug)} on ${platformName(c.platform)}`}>
      <div className="channel-head">
        <PlatformCode platform={c.platform} />
        <div className="who">
          <b>{c.handle ?? 'no handle yet'}</b>
          <span className="small muted">{platformName(c.platform)}</span>
        </div>
        <span className="right">
          {c.connected ? <span className="tag live">connected</span> : <span className="tag">not linked</span>}
        </span>
      </div>
      <div className="kv">
        <div>
          <span className="label">Posts</span>
          <span className="v">{c.posts_posted}</span>
        </div>
        <div>
          <span className="label">Views 7 d</span>
          <span className="v">{formatViews(c.views_7d)}</span>
        </div>
        <div>
          <span className="label">Median ×</span>
          <span className="v">
            <OutlierBadge x={c.median_outlier_x} />
          </span>
        </div>
        <div>
          <span className="label">Hit rate</span>
          <span className="v">{c.hit_rate == null ? '—' : `${Math.round(c.hit_rate * 100)}%`}</span>
        </div>
        <div>
          <span className="label">Follows</span>
          <span className="v">{formatViews(c.follows)}</span>
        </div>
        <div>
          <span className="label">Bar</span>
          <span className="v" style={{ fontSize: 14 }}>{c.bar_status ?? 'not yet'}</span>
        </div>
      </div>
      <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }} className="small">
          <span className="muted">Drop-in, last 10 posts</span>
          <span className="num">
            {ratioPct}% <span className="muted">of {sharePct}% share</span>
          </span>
        </div>
        <div className="meter" role="meter" aria-label="Drop-in ratio against share" aria-valuemin={0} aria-valuemax={100} aria-valuenow={ratioPct} style={{ height: 8 }}>
          <span className="fill" style={{ width: `${ratioPct}%`, background: 'var(--ink-2)' }} />
          <span className="tick" style={{ left: `${sharePct}%` }} title={`Share ${sharePct}%`} />
        </div>
        <span className="small muted">
          {c.posts_scheduled ? `${c.posts_scheduled} scheduled` : 'nothing scheduled'}
          {c.posts_problem ? ` · ${c.posts_problem} need a look` : ''}
          {c.next_slot ? ` · next slot ${londonStamp(c.next_slot)}` : ''}
        </span>
      </div>
      <div style={{ borderTop: '1px solid var(--rule)' }}>
        <AutopilotSwitch
          channel={c}
          allConnectedAuto={allConnectedAuto}
          busy={busy.has(key)}
          onToggle={(mode) =>
            run(key, () => backend.setAccountMode(c.account_id, mode), mode === 'auto' ? `Autopilot on for ${c.handle}` : `Autopilot off for ${c.handle}`)
          }
        />
      </div>
    </article>
  );
}
