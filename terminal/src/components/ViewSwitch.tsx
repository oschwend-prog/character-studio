// The switch between the views of one section (Characters | All videos, Scan · Budget · Health): the `.seg` buttons, each one
// opens its own address (so a view can be bookmarked and the back button works). `mark` is a small muted word after the label.
import type { ReactNode } from 'react';

export function ViewSwitch<T extends string>({
  label, value, options, to,
}: {
  label: string;
  value: T;
  options: ReadonlyArray<{ id: T; label: string; mark?: ReactNode }>;
  /** The address of a view (`href(...)`). */
  to(id: T): string;
}) {
  return (
    <div className="seg view-switch" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={value === o.id}
          onClick={() => {
            window.location.hash = to(o.id);
          }}
        >
          {o.label}
          {o.mark}
        </button>
      ))}
    </div>
  );
}
