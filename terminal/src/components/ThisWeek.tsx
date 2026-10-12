// Today, "This week" (learning plan 6.1, Task 16): the latest weekly review, written by the Monday cloud job (`studio review weekly`).
// The studio header (credits against the cap, the warnings, the proposals waiting), then for every live character his bar and five
// lines: Result, Audience, Hook, Tests, Next. The numbers are the code's, read as they are; "not a verdict" stays in the Tests line
// until a test reaches its look. A weekly pull request with proposals to merge shows first, because it waits for the owner.
import { ExternalLink } from 'lucide-react';
import { useMemo } from 'react';
import { useStudio } from '../lib/store';
import { emptyWeeklyNote, parseWeekly, splitLine, type WeeklyDigest } from '../lib/weekly';
import { Livery, Section } from './ui';

export function ThisWeek() {
  const { data } = useStudio();
  const week = useMemo(() => parseWeekly(data?.weekly), [data?.weekly]);
  if (!data) return null;
  return <WeekCard week={week} />;
}

/** The card itself (no store): the digest, or the one muted line when there is no review (`now` is the clock, for tests). */
export function WeekCard({ week, now }: { week: WeeklyDigest | null; now?: Date }) {
  if (!week) {
    return (
      <Section id="this-week" title="This week">
        <p className="small muted" style={{ margin: 0 }}>{emptyWeeklyNote(now)}</p>
      </Section>
    );
  }
  return (
    <Section id="this-week" title="This week" aside={<span className="num">{week.label}</span>}>
      <div className="panel rows week">
        {week.proposalUrl && (
          <a className="week-proposal" href={week.proposalUrl} target="_blank" rel="noopener noreferrer">
            <span className="tag action">Proposal waiting</span>
            <span>Merging the pull request is your approval</span>
            <ExternalLink aria-hidden="true" />
            <span className="sr-only">(opens GitHub in a new tab)</span>
          </a>
        )}
        {week.status !== 'ok' && (
          <div className="panel-pad week-problem" role="status">
            <p className="small"><span className="tag action">Review status: {week.status}</span> Part of this review did not run clean; the numbers below may be incomplete.</p>
            {week.notes.map((note, i) => <p key={i} className="small muted">{note}</p>)}
          </div>
        )}
        {week.header.length > 0 && (
          <div className="panel-pad week-head">
            {week.header.map((line, i) => <p key={i} className="small muted">{line}</p>)}
          </div>
        )}
        {week.characters.map((c) => (
          <div key={c.slug} className="panel-pad week-char" data-char={c.slug}>
            <div className="week-who">
              <Livery slug={c.slug} />
              <b>{c.name}</b>
              {c.bar && <span className="small muted">bar: {c.bar}</span>}
            </div>
            {c.lines.every((l) => splitLine(l).label == null) ? (
              <p className="small muted week-none">{c.lines.join(' ') || 'no posts yet'}</p>
            ) : (
              <dl className="week-lines" aria-label={`${c.name}, ${week.label}`}>
                {c.lines.map((line, i) => {
                  const { label, text } = splitLine(line);
                  return (
                    <div key={i} className="week-line">
                      <dt className="label">{label ?? ''}</dt>
                      <dd>{text}</dd>
                    </div>
                  );
                })}
              </dl>
            )}
          </div>
        ))}
        {week.characters.length === 0 && <p className="small muted panel-pad" style={{ margin: 0 }}>No live character was reviewed.</p>}
      </div>
    </Section>
  );
}
