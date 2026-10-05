-- ODD EYES Character Studio, migration 0003: one account per (character, platform).
--
-- Additive only, schema studio only. Applied to Supabase project hkcafvzjwkeibbmvskko
-- ("faceless-youtube") on 2026-10-05 as migration `studio_0003_accounts_unique` (the table was
-- empty, so the index could not fail), before the first `bin/studio seed` against the live database.
--
-- `studio seed` upserts accounts with `insert ... on conflict (character_slug, platform)`, which
-- needs this unique index. It also states a rule the code already relies on: planning takes "the"
-- TikTok account of a character, and `accounts()` orders by (character_slug, platform).
-- The table is empty until the owner creates the social accounts, so the index cannot fail.

create unique index if not exists accounts_character_platform_key
  on studio.accounts (character_slug, platform);
