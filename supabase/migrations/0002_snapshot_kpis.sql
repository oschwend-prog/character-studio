-- ODD EYES Character Studio, migration 0002: the two Reels KPIs on metric snapshots.
--
-- Additive only, schema studio only. Applied to Supabase project hkcafvzjwkeibbmvskko
-- ("faceless-youtube") as migration `studio_0002_snapshot_kpis`.
--
-- skip_rate   share of viewers who swiped away early (vidIQ instagram_owner_insights "skip rate")
-- watched_pct average watched percentage of the reel (vidIQ "watched percentage")
-- Both stay NULL when the platform did not report them, never 0, like every other snapshot metric.
-- The units are stored exactly as vidIQ reports them (VERIFY at go-live, Task 16).
-- RLS and the grants of 0001 already cover new columns of an existing table.

alter table studio.snapshots add column if not exists skip_rate double precision;
alter table studio.snapshots add column if not exists watched_pct double precision;
