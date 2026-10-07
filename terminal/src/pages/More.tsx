// More (terminal v2, owner 2026-10-07): what is not the daily work. Scan: the viral scan's picks (it keeps running, aside, hence the
// muted "later" mark); Budget: the month's credits and the kill switch; Health: what to look at (failed posts or clips, the daily
// run, low credits) and the Scanner. `view` is `#/more/<view>`: scan (the default and the old `#/picks`), budget (the old
// `#/budget`) or health. `account` (who is signed in, Sign out) is shown at the end of Budget.
import type { ReactNode } from 'react';
import { ViewSwitch } from '../components/ViewSwitch';
import { ScannerCard } from '../components/Scanner';
import { Skeleton } from '../components/ui';
import { href } from '../lib/hooks';
import { useStudio } from '../lib/store';
import { MORE_VIEWS, type MoreView } from '../lib/tabs';
import { Budget } from './Budget';
import { Picks } from './Picks';
import { Alerts } from './Today';

const OPTIONS = MORE_VIEWS.map((v) => ({ ...v, mark: v.id === 'scan' ? <span className="later">later</span> : undefined }));

export function More({ view, account }: { view: MoreView; account?: ReactNode }) {
  const { data } = useStudio();
  return (
    <div className="page stack">
      <div>
        <h1 className="h1">More</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          The viral scan (it keeps running, aside), the month’s budget and what to look at.
        </p>
      </div>
      <ViewSwitch label="More" value={view} options={OPTIONS} to={(id) => href('more', id)} />
      {view === 'scan' && <Picks embedded />}
      {view === 'budget' && <Budget account={account} embedded />}
      {view === 'health' &&
        (data ? (
          <>
            <Alerts />
            <ScannerCard />
          </>
        ) : (
          <div className="stack" aria-busy="true">
            <Skeleton h={120} />
          </div>
        ))}
    </div>
  );
}
