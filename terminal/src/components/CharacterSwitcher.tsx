// The character switcher: Biscuit · Reginald · All, each with its picture and livery colour. The choice is shared by
// Picks, Queue and Library, remembered per viewer (localStorage, guarded) and can come from a ?c=<slug> deep link.
import { characterFilterOptions } from '../lib/rules';
import { useCharacterFilter } from '../lib/hooks';
import { useStudio } from '../lib/store';
import { Avatar } from './ui';

const FALLBACK = [{ slug: 'biscuit', name: 'Biscuit' }, { slug: 'reginald', name: 'Reginald' }];

/** The roster the switcher offers (the seeded characters; the two launch ones until they have loaded). */
export function useRoster() {
  const { data } = useStudio();
  return data?.characters.length ? data.characters.map((c) => ({ slug: c.slug, name: c.name })) : FALLBACK;
}

export function useCharacterChoice(): [string, (v: string) => void, { slug: string; name: string }[]] {
  const roster = useRoster();
  const [value, setValue] = useCharacterFilter(roster.map((c) => c.slug));
  return [value, setValue, roster];
}

export function CharacterSwitcher({
  value, onChange, roster, counts, label = 'Character',
}: {
  value: string;
  onChange(v: string): void;
  roster: { slug: string; name: string }[];
  /** How many items each choice stands for (`all` = every one), shown as a small number. */
  counts?: Record<string, number>;
  label?: string;
}) {
  return (
    <div className="seg wide char-switch" role="group" aria-label={label}>
      {characterFilterOptions(roster).map((o) => (
        <button key={o.id} type="button" className={o.id === 'all' ? 'all' : o.id} aria-pressed={value === o.id} onClick={() => onChange(o.id)}>
          {o.id !== 'all' && <Avatar slug={o.id} name={o.label} size={24} />}
          <span>{o.label}</span>
          {counts && counts[o.id] != null && <span className="num count" aria-label={`${counts[o.id]} items`}>{counts[o.id]}</span>}
        </button>
      ))}
    </div>
  );
}
