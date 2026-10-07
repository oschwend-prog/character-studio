// The Scanner: what the daily run's scan of social media for viral videos is doing and did last (studio.runs).
import { Radar } from 'lucide-react';
import { useMemo } from 'react';
import { useNow } from '../lib/hooks';
import { nextScanLabel, scannerStatus } from '../lib/rules';
import { useStudio } from '../lib/store';
import { Section } from './ui';

function useScanner() {
  const { data } = useStudio();
  const now = useNow(30_000);
  const anyLive = Boolean(data?.characters.some((c) => c.status === 'live'));
  const status = useMemo(() => (data ? scannerStatus(data.runs, now) : null), [data, now]);
  return { status, next: nextScanLabel(now, anyLive), now };
}

const TONE_TAG: Record<string, string> = { live: 'live', alert: 'alert', neutral: '', muted: '' };

/** The Scanner card (More > Scan, and Health): state, next scan, the last scan's numbers and the vidIQ credits. */
export function ScannerCard() {
  const { status, next } = useScanner();
  if (!status) return null;
  const scan = status.last?.scan;
  const used = status.creditsMonth;
  const pct = Math.min(100, (used * 100) / status.creditsLimit);
  return (
    <Section id="scanner" title="Scanner" aside="searches TikTok and Instagram for outliers">
      <div className="panel scanner" aria-label="Scanner status">
        <div className="scanner-head">
          <Radar size={18} aria-hidden="true" className={status.state === 'scanning' ? 'pulse' : undefined} />
          <b role="status">{status.headline}</b>
          {status.state !== 'none' && <span className={`tag ${TONE_TAG[status.tone]}`}>{status.state === 'finished' ? 'idle' : status.state}</span>}
        </div>
        <span className="small muted scanner-next">{next}</span>
        {scan ? (
          <>
            <div className="kv" role="list" aria-label="Last scan">
              {(
                [
                  ['Searches', scan.queries.length],
                  ['Outliers found', scan.outliers],
                  ['Picks added', scan.picks_added],
                  ['Auto-approved', scan.auto_approved],
                  ['Held', scan.held],
                  ['Skipped', scan.skipped],
                ] as const
              ).map(([label, n]) => (
                <div key={label} role="listitem">
                  <span className="label">{label}</span>
                  <span className="v num">{n}</span>
                </div>
              ))}
            </div>
            <div className="scanner-foot">
              {scan.queries.length > 0 && (
                <div className="chips" aria-label="Searched">
                  {scan.queries.map((q) => (
                    <span key={q} className="tag">
                      {q}
                    </span>
                  ))}
                </div>
              )}
              <div className="scanner-credits small">
                <span className="muted">vidIQ credits</span>
                <span className="num">
                  {status.creditsRun ?? 0} last run · {used} of {status.creditsLimit} this month
                </span>
              </div>
              <div
                className="meter"
                role="meter"
                aria-label="vidIQ credits used this month"
                aria-valuemin={0}
                aria-valuemax={status.creditsLimit}
                aria-valuenow={used}
                style={{ height: 8 }}
              >
                <span className="fill" style={{ width: `${pct}%` }} />
              </div>
            </div>
          </>
        ) : (
          <p className="small muted scanner-empty">
            The daily run scans on Tuesday, Thursday, Saturday and Sunday and files what it finds as Viral Picks below. The numbers of each scan appear here.
          </p>
        )}
      </div>
    </Section>
  );
}
