// "How we scan": the Picks page's explanation of the scanning process, below the Scanner card and collapsed by default. What we have
// access to, what is scanned per character, the filters, the four categories with their exact rule and how many current picks each
// holds, what a video must be for us, the budget and the last scan. Static text comes from scanConfig (a copy of config/scan.json)
// and the shared tier rule: the page cannot say one thing while the scanner does another.
import { ChevronRight } from 'lucide-react';
import { useMemo, type ReactNode } from 'react';
import { useNow } from '../lib/hooks';
import { formatCredits } from '../lib/format';
import { scannerStatus } from '../lib/rules';
import {
  GLOBAL_REJECT_RULES, SCAN_ACCESS, VIDEO_REQUIREMENTS, budgetView, filterLines, lastScanView, scanCharacters, tierExamples, tierRuleLines,
} from '../lib/scanPanel';
import { useStudio } from '../lib/store';
import { Avatar } from './ui';

function Block({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="how-block">
      <h3 className="label how-title">{title}</h3>
      {hint && <p className="small muted how-hint">{hint}</p>}
      {children}
    </section>
  );
}

export function HowWeScan() {
  const { data } = useStudio();
  const now = useNow(60_000);
  const view = useMemo(() => {
    if (!data) return null;
    const status = scannerStatus(data.runs, now);
    return {
      characters: scanCharacters(data.characters.map((c) => ({ slug: c.slug, name: c.name }))),
      categories: tierExamples(data.picks, now),
      budget: budgetView(status.creditsMonth),
      last: lastScanView(status.last),
      higgsfield: data.budget,
    };
  }, [data, now]);
  if (!view) return null;
  const rules = tierRuleLines();
  const { vidiq } = view.budget;
  const examples = new Map(view.categories.map((c) => [c.tier, c]));

  return (
    <details className="stage how-scan" id="how-we-scan">
      <summary>
        <ChevronRight className="chev" aria-hidden="true" />
        <span className="stage-title">How we scan</span>
        <span className="small muted stage-hint">what we look at, what counts as viral, what a video needs</span>
      </summary>
      <div className="stage-body how-body">
        <Block title="What we have access to">
          <ul className="how-list">
            {SCAN_ACCESS.map((a) => (
              <li key={a.id}>
                <b>{a.name}</b>
                <span className="small muted">{a.what}</span>
              </li>
            ))}
          </ul>
        </Block>

        <Block
          title="What we scan"
          hint="Instagram and TikTok viral clips only: one search each weekday, Biscuit and Reginald in turn, each rotating through his themes. The Genjutsu gallery is the backup on a day the search could not run or found fewer than 2 usable clips; the first posts of a channel are Broke the internet moments."
        >
          {view.characters.map((c) => (
            <div className="how-char" key={c.slug} data-char={c.slug}>
              <div className="how-char-head">
                <Avatar slug={c.slug} name={c.name} size={28} />
                <b>{c.name}</b>
                {c.inactive && <span className="tag">{c.inactive}</span>}
              </div>
              {(c.region || c.audience) && (
                <p className="small muted how-audience">
                  {[c.region, c.audience].filter(Boolean).join(' · ')}
                </p>
              )}
              <ul className="chips how-themes" aria-label={`${c.name}’s search themes`}>
                {c.themes.map((t) => (
                  <li key={t.theme} className="tag how-theme" title={`${t.embeddingType}: ${t.query}`}>
                    {t.theme}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </Block>

        <Block title="Filters" hint="Every search keeps only videos that pass all of these.">
          <ul className="chips how-filters">
            {filterLines().map((f) => (
              <li key={f} className="tag how-filter">
                {f}
              </li>
            ))}
          </ul>
        </Block>

        <Block title="Categories" hint="The first rule that fits a video wins. A category the analyst set by hand always wins.">
          <ol className="how-tiers">
            {rules.map((r) => {
              const ex = r.id === 'fallback' ? null : examples.get(r.id);
              return (
                <li key={r.id} className={`how-tier tier-${r.id}`}>
                  <span className={`tier-badge tier-${r.id}`}>{r.label}</span>
                  <span className="small how-rule">{r.rule}</span>
                  {ex && (
                    <span className="small muted how-count">
                      <span className="num">{ex.count}</span> now{ex.example ? <>: {ex.example}</> : null}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </Block>

        <Block title="What our videos need" hint="A pick that cannot meet these is made as a Recreate instead of a Drop-in.">
          <ul className="how-list plain">
            {VIDEO_REQUIREMENTS.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <details className="how-rejects">
            <summary className="small muted">Never picked</summary>
            <ul className="how-list plain">
              {GLOBAL_REJECT_RULES.map((r) => (
                <li key={r} className="small">
                  {r}
                </li>
              ))}
            </ul>
          </details>
        </Block>

        <Block title="Budget">
          <div className="how-budget">
            <div>
              <span className="label">vidIQ</span>
              <p className="small" style={{ margin: 0 }}>
                A search costs <b className="num">{vidiq.perSearch}</b> credits{vidiq.watchesPerWeek > 0 ? <>, a watch of one video <b className="num">{vidiq.perWatch}</b></> : null}. This month: <b className="num">{vidiq.used}</b> of <b className="num">{vidiq.plan}</b> used.
              </p>
              <div
                className="meter"
                role="meter"
                aria-label="vidIQ credits used this month"
                aria-valuemin={0}
                aria-valuemax={vidiq.plan}
                aria-valuenow={vidiq.used}
                style={{ height: 8 }}
              >
                <span className="fill" style={{ width: `${vidiq.pct}%` }} />
              </div>
              <p className="small muted" style={{ margin: 0 }}>
                The plan: {vidiq.weeklyLine}.{vidiq.overPlan ? ` That is about ${vidiq.monthlyNeed} a month, more than the ${vidiq.plan} of your plan: the run watches fewer.` : ''}
              </p>
              <p className="small muted" style={{ margin: 0 }}>
                {vidiq.floorLine}.
              </p>
            </div>
            <div>
              <span className="label">Higgsfield, per clip</span>
              <ul className="how-list plain">
                {view.budget.higgsfield.map((h) => (
                  <li key={h.label}>
                    <span>
                      <b>{h.label}</b> <span className="num">{formatCredits(h.credits)}</span>
                    </span>
                    <span className="small muted">{h.note}</span>
                  </li>
                ))}
              </ul>
              {view.higgsfield && (
                <p className="small muted" style={{ margin: 0 }}>
                  This month <span className="num">{formatCredits(view.higgsfield.committed)}</span> of the <span className="num">{formatCredits(view.higgsfield.cap)}</span> cap.
                </p>
              )}
            </div>
          </div>
        </Block>

        <Block title="Last scan">
          {view.last ? (
            <div className="how-last">
              <p className="small" style={{ margin: 0 }}>
                <b>{view.last.when}</b>: {view.last.line}; <span className="num">{view.last.credits}</span> vidIQ credits.
              </p>
              {view.last.queries.length > 0 && (
                <ul className="chips" aria-label="Searched">
                  {view.last.queries.map((q) => (
                    <li key={q} className="tag">
                      {q}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <p className="small muted" style={{ margin: 0 }}>
              No scan yet: the first one appears here.
            </p>
          )}
        </Block>
      </div>
    </details>
  );
}
