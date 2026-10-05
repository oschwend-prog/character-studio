// The Traits card of a character: its energy, comedy, best formats, settings, moves, gadgets (with the viral job each one
// does), music and what it never does. Collapsible; chips for the lists. Read from characters.setup.traits (seeded from refs.json).
import { ChevronRight } from 'lucide-react';
import { traitRows } from '../lib/rules';
import type { Character } from '../lib/types';

export function TraitsCard({ character }: { character: Pick<Character, 'slug' | 'name' | 'setup'> }) {
  const rows = traitRows(character.setup?.traits);
  const id = `traits-${character.slug}`;
  if (rows.length === 0) {
    return (
      <p className="small muted" style={{ margin: 0 }}>
        No traits card yet: add <code>traits</code> to <code>characters/{character.slug}/refs.json</code> and run <code>bin/studio seed</code>.
      </p>
    );
  }
  return (
    <details className="traits stage" data-char={character.slug}>
      <summary aria-describedby={id}>
        <ChevronRight className="chev" aria-hidden="true" />
        <span className="stage-title" id={id}>Traits</span>
        <span className="small muted stage-hint">what he is like, so the daily run picks videos that fit</span>
      </summary>
      <div className="stage-body traits-body">
        {rows.map((r) => (
          <div className="trait" key={r.key}>
            <span className="label">{r.label}</span>
            {r.kind === 'text' ? (
              <p className="small" style={{ margin: 0 }}>{r.values[0].text}</p>
            ) : (
              <ul className="trait-chips">
                {r.values.map((v) => (
                  <li key={v.text} className={`trait-chip${v.hint ? ' has-hint' : ''}${r.key === 'never' ? ' never' : ''}`} title={v.hint}>
                    <span>{v.text}</span>
                    {v.hint && <span className="chip-hint">{v.hint}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}
