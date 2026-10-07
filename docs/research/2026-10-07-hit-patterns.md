# ODD EYES: hit patterns, 7 Oct 2026

**What this is:** what makes short videos hit right now (posts from about 5 Aug to 7 Oct 2026), turned into production
rules for our Drop-ins. It builds on `2026-10-04-niche-playbook.md` and `2026-10-05-best-practice-audit.md` and does not
repeat them. Where it changes them, it says so.

**Who reads it:** the owner; the `viral-hook-creator` skill (through `FOUNDER_CONTEXT.md`, which points here); and
whoever wires the rules into `studio/gemini.py`, `config/scan.json` and the daily run (section 7).

**Labels:**
- **[E]** = measured or sourced. The source is named in brackets.
- **[I]** = my inference.
- Source tags:
  - **(LC)** = the social-data MCP (LunarCrush), queried 7 Oct 2026.
  - **(VQ-W)** = vidIQ watch breakdowns made on 4 Oct, read again for free on 7 Oct.
  - **(VQ-O)** = vidIQ outlier data from the 4 Oct scans, as recorded in the playbook.
  - **(WEB)** = a named article (listed under Sources).

**Limits of this research (read first):**
- **vidIQ had 3 credits** (plan refills 4 Nov). A search costs 5 credits and a watch costs 10, so no new vidIQ search or
  watch was possible. 0 credits were spent; every vidIQ call was free (the balance, the job list, the bookmarks and 7 polls
  of old watch jobs). The owner then switched the source to LunarCrush.
- **LunarCrush is in "limited data mode".** Each query returns at most 4 posts. It reports "engagements" (its own total,
  which may include views), not views, and it gives no outlier score. Where I give a multiple for an LC post, it is
  **engagements ÷ followers**: a rough proxy, not vidIQ's outlier ×. I made 25 calls; 7 returned an error or nothing.
- **Nothing was downloaded or watched by me.** The `last30days` skill was not run: it reaches TikTok and Instagram through
  ScrapeCreators or Apify, and its setup installs yt-dlp and reads browser cookies. That breaks our no-scrape rule.
- The "post" tool returns a raw video CDN link. I did not open it and it is not recorded here.

---

## 0. The rules in 10 lines

1. **Pick a clip whose star is already moving in its first second and pays off by second 3**: one performer, one static shot, full body.
2. **Rank dog clips by reach ÷ followers, not raw views.** This month's biggest dog hits came from accounts with 2.6K-42K followers.
3. **Use a trend's curve, not its date.** File a trend pick only if it peaked 7 days ago or less, or still runs at 50% or more of its peak (classics exempt). One free LunarCrush call checks it.
4. **Drop into trends many people do, never into another creator's own character skit.** Never use the same creator twice in 30 days.
5. **Trim:** start 0.3 s before the first big move, keep the payoff inside the window and end on a beat in a pose close to the first frame, so it loops. Keep the owner's lengths: 8-10 s, classics 12-15 s.
6. **Hook pill:** at most 7 words and 42 characters, one claim the clip proves within 3 s. Franz speaks in the first person, Reginald gives a calm label, Lenny is caught mid-deal. One hook in three names the trend.
7. **Caption line 1 = the trend's exact name + edition, at most 30 characters**, so the joke shows before "more". Hashtags: the trend, the niche, the format, #oddeyes and the character's own tag.
8. **The first comment is a two-option vote for the next clip**, in the character's voice. The owner makes the winner.
9. **Keep the clip's own sound when it is the trend sound.** Prefer clips carrying a sound that is rising now.
10. **Judge a post at 72 h and 7 days, never at 1 h.** The two biggest dog hits had their best hour 39-41 h after posting. Each character runs one numbered series.

---

## 1. What changed since the 4 Oct playbook

- **Franz is a happy show-off now** (owner 7 Oct). But `config/scan.json` still searches for "unimpressed dog" and "posh dog
  day-in-the-life", and its fit rules still say "dignified and permanently unimpressed … nothing athletic". Franz's bible
  `## Voice (captions)` still has posh examples, and his first comment is still "Requests may be submitted to my staff. In
  writing." **`studio/gemini.py` feeds that section to Gemini**, so Franz's drops will get posh captions until the bible
  section is rewritten. [E: read in the repo]
- **"Single Ladies" has peaked.** On TikTok it hit 1.14-1.16M engagements a day on 2-3 Oct, then fell to 332K on 6 Oct
  (−71%). The playbook's "drop it by about 20 Oct" becomes **"make it by 10 Oct or skip"**. [E (LC)]
- **The "hot dog dance" (an NFL celebration) is dead.** It peaked at 2.69M a day on 21 Sep and was at 17K on 7 Oct (−99%).
  It is the worked example for rule P5. [E (LC)]
- **Gangnam Style is rising.** It is a classic, and its TikTok engagements went from about 0.4-1.0M a day in mid-Sep to
  2.4M on 5 Oct and 3.4M on 6 Oct, the highest of the month. [E (LC)]
- **There is no eye close-up end any more** (owner 5 Oct). The playbook's loop ("end on the eye stare, cut back to the same
  stare") no longer applies. The loop now has to come from the dance itself (rule T3). [E: CLAUDE.md]
- **@clivecheckingin's black-tie character clip kept growing**: 1.9M views on 4 Oct (VQ-O), then 4.4M engagements on 7 Oct (LC).
  It is the clearest live model for a daily character series with a vote (rule F1).

---

## 2. Evidence

### 2.1 Top posts in our lanes, last 30 days (LC, 7 Oct)

| Post | Platform, date | Followers | Engagements | Eng ÷ followers | What it is |
|---|---|---|---|---|---|
| @king_odiee | TikTok, 4 Oct | 41.5K | 29.3M in 4 days | ~707 | Dachshund doing a famous pop dance. Caption: "I learned some new dance moves from my girl" + the singer's tag. Best hour 5 Oct 18:00 UTC, 41 h after posting |
| @gogoretriever | TikTok, 29 Sep | 39.7K | 25.7M in 9 days | ~647 | Golden retriever dance. "Pajamas on, attitude louder 🐶". Best hour 30 Sep 15:00 UTC, 39 h after posting |
| @strandfarmdiaries | TikTok, 1 Oct | 2.6K | 12.8M | ~4,800 | Dachshund at a marathon. "When your mum has the audacity to kiss dad and not you" |
| @jaaan77772 | TikTok, 18 Sep | 9.2K | 9.4M | ~1,000 | Dog dancing with men on a road |
| @itsbeantheween | TikTok, 6 Oct | 4.0K | 3.3M in about 1 day | ~825 | Mini dachshund; the caption is one emoji (content unknown) |
| @foolish.p | Instagram, 26 Sep and 8 Sep | 4.5K | 1.6M and 1.5M | ~350 | Golden retriever dancing in the street to film songs: two hits in one month from one small account |
| @clivecheckingin | TikTok, 2 Oct | 55.9K | 4.4M | ~79 | Black-tie character comedy. "Who steals the show from him tomorrow? Vote" |
| @trxineex | TikTok, 2 Sep | 364.9K | 29.7M | ~81 | Group "water dance" challenge to a pop song (studio choreography) |
| @userissav | TikTok, 5 Oct | 8.5K | 1.6M in 2 days | ~187 | "Giddy up! 🤠🐎", a new two-person dance |
| @feelcrew_official | Instagram, 3 Oct and 26 Sep | 966K | 12.9M and 7.8M | ~13 and ~8 | Five-man street remakes of Gangnam Style |
| @brotherhoodcrew | TikTok, 25 Sep | 434.7K | 2.1M | ~5 | Gangnam Style crew choreography |
| ESPN / SportsCenter | TikTok and IG, 20-22 Sep | 39-61M | 2.8-4.5M | <1 | NFL "hot dog dance" on TV footage: not usable |

Searches that returned nothing useful:
- "deadpan" returned TV-show scene clips: real actors, so not usable.
- "boss", "office", "butler", "on the phone", "ai character", "ai dance", "corporate", "charactercomedy", "unbothered",
  "my boss" and "dog costume" returned an error or nothing in limited mode.
- **So the Reginald and Lenny lanes rest on the 4 Oct vidIQ data (VQ-O) and the web reports.**

### 2.2 Trend curves (LC `keyword_time_series`, all networks, daily)

| Keyword | Peak (day, engagements) | Latest (day, engagements) | Change | Stage |
|---|---|---|---|---|
| gangnam style | 6 Oct, 5.47M (TikTok 3.43M) | 6 Oct | rising since 2 Oct | **rising** (a classic) |
| single ladies | 3 Oct, 1.63M (TikTok 1.16M) | 6 Oct, 456K (TikTok 332K) | −72% in 3 days | **fading**, last call ~10 Oct |
| ramalama | 2 Oct, TikTok 461K | 5 Oct, TikTok 228K | −51% in 3 days | **peaked; a 2nd wave is likely before Halloween [I]** |
| hot dog dance | 21 Sep, 2.69M | 7 Oct, 17K | −99% in 16 days | **dead** |

### 2.3 Old vidIQ watch breakdowns (VQ-W, made 4 Oct, read for free)

Seven jobs existed. Four tell us something about our formats:

| Clip | Length | First 3 s | Structure | Lesson |
|---|---|---|---|---|
| instagram.com/reel/DbdfIyOo_cf (785× median) | 14.0 s | the diver is already plunging at 0:00; one text line | **one continuous static shot**; the first flip lands on the vocal shift at 0:04-0:05; loops back to the top | one shot, a move at frame 0, a loop |
| tiktok.com/@xy_shortdrama.yn01/video/7690387697302654229 | 24.5 s | calm at 0:00, explosion at 0:01, **unbothered reaction** at 0:02-0:03; no text | 11 cuts | calm-vs-chaos is a hook by itself. Too many cuts to swap |
| tiktok.com/@biular/video/7670256132455238933 | 20.6 s | a deadpan glare at 0:02-0:03; muffled audio, then the **beat drops at 0:03** | ends where it started, in the kitchen, so it loops | drop at 3 s; loop to the first frame |
| instagram.com/reel/DbgmnsDqmn9 | 11.8 s | one confession line pinned for the whole clip | 4 shots; loops | one line of text can carry a whole clip |

The other three (59 s and 78 s AI serial episodes, a 21 s mood piece) are not our format. They do show title cards like
"EPISODE 03", which supports numbered series.

### 2.4 Web trend reports (WEB)

| Trend | Platform, week | Format | Source |
|---|---|---|---|
| Be OK (Ingrid Michaelson) | TikTok + IG, Oct | happy dance; on-screen text tells the chaotic truth; under 15 s | NewEngen (TikTok, updated 5 Oct; IG, 1 Oct) |
| Ramalama costume walk / "Did I win this trend?" | TikTok + IG, Oct | low-angle walk-in, then the full costume is revealed on the drum drop; **430.7K videos** | NewEngen; SocialPilot (5 Oct) |
| Things You Should Definitely Ghost | IG, Oct | a sheet ghost holds signs naming bad habits; 4-6 clips | NewEngen IG |
| My Reaction To ___ | IG, Oct | escalating numbers with escalating reactions, 3-5 rounds | NewEngen IG |
| Viral dance fit check, "Bow Bow Bow" (Zeddy Will) | TikTok, Oct | dance plus outfit reveal; **246K videos** | SocialPilot |
| 31 Days of Halloween | TikTok, Oct | a numbered daily series | SocialPilot |
| How Could This Day Get Any Better | TikTok, Sep | deadpan "oh boy, a [thing]", then a bass drop reveals the upgrade | NewEngen (Sep, updated 21 Sep) |
| Bass Persuades dance | TikTok, Sep | unhinged full-body dancing to "kids don't wanna dance" | NewEngen Sep |
| Absurd-rule service skit | IG, summer | a deadpan service-counter rule, about 50M views | Anijam (27 Jul) |
| "Netflix documentary" chair-sit | IG, summer | a mundane subject treated with total gravity and a swelling score | Anijam; mean.ceo |
| Sounds now | TikTok, 5 Oct | "Patient Zero" rising (149.3K videos); "we fell in love in october" at peak (1.8M); "DIP ON EM" early (49.3K) | SocialPilot |
| Halloween | both | Halloween is on **Saturday 31 Oct**, so costume content gets a whole weekend to peak | NewEngen |
| Gangnam Style in Spanish | TikTok + IG, 22 Sep | a creator's Spanish version passed 3.5M plays | El Comercio [single source] |

### 2.5 Platform mechanics checked this week

- **Skip rate** on Instagram is the share of viewers who scroll past within the first 3 seconds, and it replaced "view
  rate" [E (WEB: Metricool, Feb 2026)]. Practitioner benchmark: 30-40% is healthy and above 50% loses reach. There is no
  official figure [E-weak (WEB: TrueFutureMedia, inro)].
- **Replays count as views** on Instagram. Ranking leans on completion and replays [E-weak (WEB: socialcrawl, measured 425 posts)].
- **Audio.** Instagram's ranking predicts whether a viewer will "go to the audio page" [E (WEB: Chartlex, citing Instagram's
  ranking explainer)]. Mosseri said in a July 2026 AMA that using popular audio carries no penalty [E-weak (WEB)].
- **Length.** On TikTok, 7 s clips complete 89% of the time, 15 s clips 73% and 30 s clips 55%. But 15 s clips earn more
  watch time per view (10.9 s vs 6.3 s) [E-weak (WEB: ttcalculator, method unclear)].
- **Text hooks** of 5-8 words, readable in one glance. The Reels hook window is 1.0-1.5 s [E-weak (WEB: Skeepers, ClipSpeed)].
- **Reskin backlash.** The AI influencer Nia Noir reached 332M views on one dance, then was accused of reskinning a
  TikToker's dance videos [E (WEB: Know Your Meme)].

---

## 3. What the hits have in common

1. **The animal talks in the first person, with attitude.** "Pajamas on, attitude louder." "I learned some new dance moves
   from my girl…" "I'm not a food thief… I'm a taste inspector" (550.7×, VQ-O). The three biggest dog captions of the
   month are first-person ego lines, not descriptions. [E (LC, VQ-O)]
2. **"When …" makes it relatable and sendable.** "When your mum has the audacity to kiss dad and not you" reached ~4,800×
   followers. "When the beat drops and suddenly nobody remembers you're supposed to be a dog" reached 221.8× (VQ-O). [E]
3. **Small accounts win with one animal and one moment.** Five dog posts from accounts with 2.6K-42K followers reached
   3-29M engagements in 30 days. Follower count is not the gate; the clip is. [E (LC)]
4. **A famous dance or sound does the discovery.** The biggest dachshund clip rides a famous pop dance. The dance's keyword
   peaked on the same days. Gangnam Style remakes are climbing. [E (LC)]
5. **Movement or contrast in second 0-1, and the payoff by second 3.** The 785× diving clip starts mid-plunge. The
   short-drama hit cuts calm → explosion → unbothered in 3 s. The kitchen hit drops the beat at 0:03. [E (VQ-W)]
6. **One continuous shot that loops.** The two looping single-shot hits ran 12-14 s. Clips with 8-23 cuts were stories,
   not loops, and could not be swapped. [E (VQ-W)]
7. **Trends now live about 5-10 days.** Single Ladies fell 72% in 3 days. Ramalama fell 51% in 3 days. The hot dog dance
   fell 99% in 16 days. Only classics come back. [E (LC)]
8. **Character comedy wins with a series and a vote.** Clive posts one outfit and one action per day and asks "who steals
   the show tomorrow?". He went from 1.9M to 4.4M in 3 days. [E (LC, VQ-O)]

---

## 4. Production rules

Each rule has an ID, a label, the evidence and a **test** (how the weekly review or a check can prove or kill it). The
binding KPI bars in `channel-strategy.md` §3.3 are unchanged. These rules only decide what we make.

### 4.1 Which clips to pick (P)

- **P1 [E] The star moves in the first second of the source.** Evidence: section 3.5.
  - Test: the deconstruct reports `first_move_s` ≤ 1.0 into the chosen window; a pick that fails gets feasibility −2.
- **P2 [E] One continuous, static shot that covers the whole window**, with one performer in full body. Evidence: 3.6; it
  already is the playbook rule.
  - Test: zero cuts inside the window; `camera` = static.
- **P3 [E] Rank dog clips by reach ÷ followers when vidIQ's outlier score is missing.** Evidence: 3.3.
  - Test: file a dog pick only at engagements ÷ followers ≥ 100 (LC proxy) or vidIQ outlier ≥ 5.
- **P4 [I] Prefer a dance or moment with a name people search.** The name feeds caption line 1, hook H6 and the
  hashtags. Evidence: 3.4.
  - Test: at least 70% of filed picks have a non-empty `moment_name`; the weekly review compares outlier_x for named vs unnamed.
- **P5 [E] Check freshness on the curve, not by the post date.** File a trend pick only when:
  - (a) the trend's peak day was 7 days ago or less; or
  - (b) its latest day is still at least 50% of its 30-day peak; or
  - (c) it is a classic (tier `iconic`).
  - Check it with one LunarCrush `keyword_time_series` call (interval 1m; free). Evidence: section 2.2.
  - Test: store `days_since_trend_peak` at filing; the weekly review compares outlier_x by bucket (0-3, 4-7, 8+ days).
- **P6 [E] Drop into trends that many people do. Never into another creator's own character or signature skit**, and
  never the same creator twice in 30 days. A trend counts when its sound has 10K+ videos or the moment is a classic.
  Evidence: Nia Noir's reskin backlash (WEB); Instagram's originality rule (audit #1).
  - Test: zero repeated creator handles over 30 days (`fav seen` + `creator`).
- **P7 [I] No TV, broadcast or sports-feed footage.** It is multi-camera, shows real public figures and has rights holders
  (e.g. the ESPN hot dog dance; "deadpan" searches returning TV-show scenes). This adds to `global_reject_rules`.
- **P8 [I] For text-led trends** (Be OK, My Reaction To, Things You Should Definitely Ghost), pick a clean clip with the
  trend's sound and no text. Our pill and 2-3 `text_pop` lines carry the joke. The source must have `has_overlay=false`
  anyway.
- **P9 [I] Franz now takes upright dog dances.** The 7 Oct look dances upright (bodies biped + quadruped). The biggest dog
  hits are dogs "doing" a human dance. `config/scan.json` still says "nothing athletic". That fit rule is the owner's to
  update.

### 4.2 The trim window (T)

- **T1 [E] The payoff lands by second 3 of the window.** Start the window 0.3 s before the first big move, never earlier.
  If the payoff (the drop, the reveal, the big move) comes more than 3 s into the window, cut the run-up. Evidence:
  section 3.5; skip rate is measured on the first 3 s (2.5).
  - Test: `payoff_s - window.start_s` ≤ 3.0; the weekly review compares the 3 s hold / skip rate for in-rule vs out-of-rule clips.
- **T2 [E] Keep the owner's lengths.** 8-10 s for normal clips and 12-15 s for classics, 16 s at most. The looping hits
  ran 12-14 s, and 15 s holds more watch time than 7 s (2.5). Nothing here argues for a change.
- **T3 [I] End so it loops.** Among windows with equal motion, take the one whose last 0.5 s is closest in pose and energy
  to its first 0.5 s. Replays count as views on Instagram (2.5). The eye close-up loop is gone, so the dance must make the loop.
  - Test: tag `seamless_loop`; the weekly review compares watch ratio (above 1.0 means replays).
- **T4 [I] End on a beat, mid-move.** Never end on a held still, a fade or a pause. The master already ends on the dance;
  this adds "on a beat".

### 4.3 The hook pill (H)

These are the hook rules that `FOUNDER_CONTEXT.md` applies. They add to its binding rules (42 characters, true to the
clip, never explain, no real names).

- **H1 [E] At most 7 words and 42 characters**, on screen from frame 0, readable in one glance. Evidence: 5-8 words max and
  a 1.0-1.5 s Reels hook window (2.5).
- **H2 [E] One claim, proved within 3 s.** The clip must pay the hook off by `payoff_s` (rule T1). A hook about something
  that happens at second 8 fails.
- **H3 [I] One of the three candidates names the trend or moment** (e.g. "Gangnam Style, butler edition"). On-screen text is
  indexed for search (playbook 4.1). The other two use a character pattern.
- **H4 [E] Keep the bans:** no "POV:", no "wait for it", no greeting, no AI talk. A top false-premise hit did use "POV:"
  (3,474.7×, VQ-O). The **"When …" frame** gives the same relatable set-up in fewer characters.

**Patterns** (name each candidate with one; the `hook_pattern` tag uses these names):

| Pattern | What it does | Evidence | Fits |
|---|---|---|---|
| `ego-claim` | First person, proud, the clip proves it | "Pajamas on, attitude louder" 25.7M; "I learned some new dance moves…" 29.3M (LC) | Franz |
| `when-relatable` | "When …" + a situation the viewer knows | ~4,800× (LC); 221.8× (VQ-O) | Franz, Lenny |
| `false-premise` | A calm label for a job, then the drop | "first day as an assassin" 1,392.8× (VQ-O) | Reginald |
| `understatement` | Calm words under a wild moment | the unbothered-explosion hit (VQ-W) | Reginald |
| `mid-deal` | Start mid-argument, the trend is the answer | Lenny's locked template; the calm-vs-chaos cut (VQ-W) | Lenny |
| `trend-label` | Names the trend or classic | rising named trends (LC) | all (one in three) |
| `myth-bust` | "they said X can't" | playbook | Franz |

**Example hooks (each at most 7 words and 42 characters):**

**Franz** (happy show-off, first person, bouncy; "Sausage coming through!"):
1. `Sausage coming through!` (signature)
2. `Learned it in one try. Obviously.` (ego-claim)
3. `The humans practised. I just showed up.` (ego-claim)
4. `Short legs. Zero problems.` (myth-bust)
5. `When the beat drops, I'm the lead` (when-relatable)
6. `Single Ladies, dachshund edition` (trend-label; only until ~10 Oct)

**Reginald** (a calm label or a butler's understatement; may name the dance, his own lines never do):
1. `First day as head butler.` (false-premise)
2. `Tea is served at four. Then this.` (false-premise)
3. `The household is unaware.` (understatement)
4. `Not a hair moved. As usual.` (understatement)
5. `Sir requested something seasonal.` (understatement)
6. `Gangnam Style. Butler edition.` (trend-label)

**Lenny** (agent-speak in short bursts, capitals, then smug calm; "You're welcome."):
1. `They put me on HOLD. Again.` (mid-deal)
2. `Offer's off the table at NOON.` (mid-deal)
3. `I don't do "maybe". I do THIS.` (ego-claim)
4. `When the client says "let's circle back"` (when-relatable)
5. `Twenty years in this business. Watch.` (mid-deal)
6. `Gangnam Style. Agent edition.` (trend-label)

### 4.4 Caption first line, keywords and hashtags (C)

- **C1 [E/I] Line 1 = the trend's exact name + the edition, at most 30 characters** (the cap is 40 today).
  - Examples: "Gangnam Style · butler edition", "Single Ladies · dachshund edition".
  - Why: one search phrase in the caption and the on-screen text helps Instagram search [E-weak (WEB: mean.ceo)]. A shorter
    label lets line 2, the joke, show before "more" [I].
- **C2 [E-weak] Five hashtags:** `#<trend>` first, then `#<niche>`, `#<format>`, `#oddeyes` and **the character's own tag**
  (e.g. `#franzthedachshund`, `#reginaldthebutler`, `#lennygold`; the owner picks the names).
  - Evidence: the dog hits all carry breed and trend tags, and the black-tie character hit carries its own name tag (LC). One
    creator is weak evidence; the own tag also gives fans one place to binge.
  - The bans stay (#fyp and the rest). The hits use #fyp, but nothing shows it causes reach.
- **C3 [I] Test joke-first against label-first on Instagram.** The TikTok hits lead with the joke, while our formula leads
  with the label. Tag `caption_first_line_pattern` and alternate per character.
  - Test: the weekly review compares the two (the binding hook-pattern bar applies: proven at 2 hits in 10 uses).

### 4.5 The first comment (F)

- **F1 [E-weak] A two-option vote for the next clip, in the character's voice.** Clive's live hit ends "Who steals the show
  from him tomorrow? Vote" (4.4M, LC). The owner makes the winning drop, which closes the loop from comment to video.
  - Franz: `Next one: Gangnam Style or the Ramalama walk? I'll win either. 🌭`
  - Reginald: `Next week: the Macarena or Gangnam Style. Kindly vote below. 🎩`
  - Lenny: `Two offers on the table. Gangnam or Single Ladies. You have till NOON. 📞`
  - Test: comments per 1K views, vote posts vs the others (the weekly review).
- **F2 [E] Rewrite Franz's first comment.** "Requests may be submitted to my staff. In writing." is the retired posh voice
  (section 1).

### 4.6 Sound, loops and endings (S)

- **S1 [E] Keep the clip's own audio when it is the trend sound.** Instagram ranks on "go to the audio page", and popular
  audio carries no penalty (2.5). This confirms the owner's `original` default for Drop-ins.
- **S2 [E] Prefer clips whose sound is rising now:**
  - Patient Zero (rising);
  - "we fell in love in october" (at peak);
  - DIP ON EM (early);
  - Bow Bow Bow (dance fit check);
  - Ramalama (Halloween);
  - Be OK;
  - Gangnam Style (rising classic).

  Give such a pick freshness +2 [I]. Refresh this list weekly from the trend reports or an LC time series.
- **S3 [E] When Instagram mutes the song**, use the existing `in_app` fallback with the same song. It is the same sound the
  trend runs on.
- **S4 [I] Loops and endings:** see T3 and T4. No sting, no fade, no silence at the end.

### 4.7 Series and repeatable formats (R)

Evidence: numbered series outliers at 13-236× (VQ-O, playbook V6); Clive's daily episodes (LC); "Tassle Tuesday" (VQ-O);
"31 Days of Halloween" (WEB).

| Character | Series | Format | Episode card (caption line 2 or the tease) |
|---|---|---|---|
| Franz | **Sausage vs the trend · Day N** | this week's named dance, done better than the humans in the clip | "Day 4. The humans are taking notes." |
| Reginald | **The household is unaware · No. N** | one trend, one room; resumes service | "No. 7. The wine cellar. As you were." |
| Lenny | **On hold · Day N** | every clip opens mid-call; the trend is what he does while on hold | "Day 3 on hold. Still winning." |
| All | **Classics** (butler / agent / dachshund edition) | one classic a week while its curve is up; Gangnam Style first | label in line 1 |
| All, 19-31 Oct | **Halloween countdown · N days** | costume walk (Ramalama), ghost signs | "9 days to Halloween." |

Test: follows per 1K views for series posts vs one-offs (the KPI is already defined).

### 4.8 Timing and cadence (only what the evidence changes)

- **No slot change.** The data does not argue against 12:30, 19:00 and 19:30 London. [I]
- **Judge late. [E (LC)]** The two biggest dog hits had their best hour 39 h and 41 h after posting.
  - Never delete or repost a slow starter before 72 h.
  - The 1 h pull is for monitoring only. The 7 d outlier_x stays the binding figure.
- **Halloween is on a Saturday [E (WEB)].** Costume content peaks over that weekend, but our cadence is Mon-Fri.
  **Owner decision:** one extra post per character on Sat 31 Oct (inside the 2-a-day cap), or the Halloween clips land on
  Thu 29 and Fri 30 Oct.

---

## 5. Clips to save (for the owner)

The owner saves these himself, in the app or by dropping the link on the terminal. We never download them. Before Make it,
the drop's own check confirms one performer, a static camera, no burned-in text or watermark, and an adult star (a dog is
fine).

**Columns:**
- **Proof** = views and vidIQ outlier × (VQ-O), or engagements and the engagements ÷ followers proxy (LC).
- **Check** = what to confirm before saving.

| # | Platform | URL (as returned) | Proof | Why it hit | Fits | Check |
|---|---|---|---|---|---|---|
| 1 | TikTok | https://www.tiktok.com/@king_odiee/video/7692606728323583246 | 29.3M eng in 4 days, ~707 (LC) | same breed; a famous pop dance; first-person ego caption | **Franz** | one dog, static camera; Single Ladies is fading, so **make by ~10 Oct** |
| 2 | TikTok | https://www.tiktok.com/@gogoretriever/video/7690745166033997086 | 25.7M eng, ~647 (LC) | outfit + attitude line; dog dance | **Franz** (his streetwear fits "pajamas on") | full body; the outfit swap |
| 3 | TikTok | https://www.tiktok.com/@jaaan77772/video/7686982135818898709 | 9.4M eng, ~1,000 (LC) | a dog dancing with men on a road: the tiny dog out-dances the humans | **Franz** | the dog is the star; camera |
| 4 | TikTok | https://www.tiktok.com/@strandfarmdiaries/video/7691677044467305750 | 12.8M eng, ~4,800 (LC) | "When your mum has the audacity…": a jealous dachshund | **Franz** (pet comedy; he wants the spotlight) | likely handheld at a marathon; may fail P2 |
| 5 | TikTok | https://www.tiktok.com/@itsbeantheween/video/7693625795557805342 | 3.3M eng in ~1 day, ~825 (LC) | the freshest dachshund outlier (6 Oct) | **Franz** | content unknown (emoji caption); watch first |
| 6 | Instagram | https://www.instagram.com/p/DdwISn7OPe4 | 1.6M eng, ~350 (LC) | a dog dancing in the street; the same creator hit twice this month | **Franz** | the song may be muted on IG; full body |
| 7 | Instagram | https://www.instagram.com/p/DdBy9mAOq6j | 1.5M eng, ~280 (LC) | the second hit of the same format | **Franz** (only one of 6 and 7: rule P6) | as above |
| 8 | TikTok | https://www.tiktok.com/@banana.the.wiener/video/7673905586383113503 | 1.4M views, 131.8× (VQ-O) | a long-haired dachshund, 5 s micro-loop | **Franz** | 5 s is short: the window needs 6 s or more |
| 9 | TikTok | https://www.tiktok.com/@lola.thestaffy/video/7679128537311251734 | 2.8M views, 221.8× (VQ-O) | costume + "when the beat drops… nobody remembers you're supposed to be a dog" | **Franz** | a dog star; no burned-in caption in the window |
| 10 | TikTok | https://www.tiktok.com/@tillandsialover/video/7688386199270001953 | 7.4M views, 1,177.5× (VQ-O) | an upright pet hits every beat | **Franz**, if the pet is a dog | the species; the gesture-heavy moves |
| 11 | Instagram | https://www.instagram.com/reel/Dd1koUkoXgq/ | 12.8M views, 550.7× (VQ-O) | a dachshund with a "job" ego caption | **Franz** (pet comedy) | one dog; camera |
| 12 | Instagram | https://www.instagram.com/reel/Dde-rPWCOC6/ | 43.4M views, 1,392.8× (VQ-O) | false premise, a mundane task, then the drop | **Reginald** | the star is an adult; few cuts |
| 13 | Instagram | https://www.instagram.com/reel/DdZCANpDgI2/ | 5.6M views, 3,474.7× (VQ-O) | a barista breaks into a dance for her favourite song | **Reginald** (service + drop) | who the star is; the background people are fine |
| 14 | TikTok | https://www.tiktok.com/@realmrmotivator/video/7669427457178488086 | 349.7K views, 291× (VQ-O) | the elder out-dances the young | **Reginald** | the adult star; the young are background only |
| 15 | TikTok | https://www.tiktok.com/@watdahektor/video/7679578183359941918 | 789K views, 280.3× (VQ-O) | "the urge … took over at work" | **Reginald** or **Lenny** | setting decides: service → Reginald, office → Lenny |
| 16 | Instagram | https://www.instagram.com/reel/DcREZSzowjZ/ | 5.2M views, 422.3× (VQ-O) | a man in a suit dances in an office lobby | **Lenny** (like for like: a man in a suit) | full body; static camera |
| 17 | TikTok | https://www.tiktok.com/@augustdrews/video/7675389374896295199 | 4.7M views, 8.5× (VQ-O) | the "Tassle Tuesday" weekday series | **Lenny** (the same creator as #16: use only one, rule P6) | as above |
| 18 | TikTok | https://www.tiktok.com/@bharles7/video/7677766296813030686 | 1.9M views, 34× (VQ-O) | a uniform at work + a trend dance | **Lenny** or **Reginald** | the uniform type |
| 19 | TikTok | https://www.tiktok.com/@brotherhoodcrew/video/7689604691734416658 | 2.1M eng, ~5 (LC) | Gangnam Style crew choreography (a rising classic) | **Reginald** / **Lenny** | **multi-body: held** (`needs multi_body`) until the multi-body test passes; better, find a solo Gangnam clip |
| 20 | Instagram | https://www.instagram.com/p/DeCLAiAunT_ | 12.9M eng, ~13 (LC) | Gangnam Style remake by a five-man crew | **Reginald** / **Lenny** | multi-body: held, as #19 |

**Watch only, don't drop into:**
- https://www.tiktok.com/@clivecheckingin/video/7692136677719969054 (4.4M eng): another creator's own character; study
  the series and vote format (rule P6).
- https://www.tiktok.com/@trxineex/video/7681059329612467463 (29.7M eng): a studio choreography in water; splashes and a group
  make it a poor swap.
- https://www.tiktok.com/@userissav/video/7693312140152687885 (1.6M eng in 2 days): a new two-person dance; multi-body.

**Excluded:**
- the ESPN / SportsCenter hot dog dance: TV footage, real athletes, a dead trend;
- @jaysjabber's Gangnam Style blooper: an impression of a real reporter;
- @muduronline's Single Ladies dog (playbook): already an AI output (`kind = synthetic` is not a Drop-in source);
- TV-show "deadpan" scenes: real actors.

**Total: 20 clips to save, 3 to watch only.**

---

## 6. Next four weeks [I]

| When | Character | What |
|---|---|---|
| Now - 10 Oct | Franz | Single Ladies (clip 1) or skip it |
| Now - while rising | Reginald, Lenny | Gangnam Style, solo clip only (check the curve weekly) |
| 13-24 Oct | all | Be OK (happy dance + our text pops); "My Reaction To ___" for Lenny with offer numbers ("$10K… $10M") |
| 19-31 Oct | all | Halloween countdown: Ramalama costume walk (Franz in a costume, Lenny on the phone in a costume); "Things you should definitely ghost" for Reginald (the quiff through the sheet; check that the sign text is not flagged as burned-in) |
| Weekly | all | Refresh the rising-sounds list (S2) and check every filed trend's curve (P5) |

---

## 7. How to wire this into the studio (proposals only; nothing was changed)

1. **`studio/gemini.py`, the deconstruct**
   - Add to `DECONSTRUCT_SCHEMA`:
     - `first_move_s` and `payoff_s` (seconds into the clip);
     - `trend_sound` (the named sound or song, "" when none);
     - `text_led` (bool: the trend's joke needs on-screen text);
     - a `pattern` per hook, from the table in 4.3.
   - Prompt changes:
     - add H1-H4 and the pattern table to the hooks paragraph;
     - "one of the three names the moment when `moment_name` is set";
     - the title uses `moment_name` verbatim, at most 30 characters;
     - first_comment = a two-option vote for the next clip.
   - `deconstruct_problems`: refuse a hook over 7 words, and a title over 30 characters when a moment is named.
2. **`studio/drop.py`, `drop_window`**
   - Keep `payoff_s` inside the window, with `payoff_s - start_s` ≤ 3.0.
   - Start no earlier than `first_move_s - 0.3`.
   - Among windows of equal energy, prefer the end whose motion matches the start (T3).
   - The existing energy, cut and beat logic stays.
3. **Bibles (owner)**
   - Rewrite Franz's `## Voice (captions)`, examples, first comment and `## Search keywords` ("posh dog" → "dancing
     dachshund", "dog dance", "sausage dog") for the happy show-off. Gemini reads these sections verbatim.
   - Add each character's own hashtag (C2).
4. **`config/scan.json` (owner)**
   - Replace Franz's rotation themes and fit rules:
     - themes "dog nails a famous dance", "dog with attitude", "dog out-dances the humans" and "dog costume walk";
     - allow upright dog dances (P9).
   - Add a P5 freshness rule and P7 (no TV or broadcast footage) to `global_reject_rules`.
   - Note that vidIQ is at 3 credits until 4 Nov, so the daily search skips (balance under `balance_floor`).
5. **`.claude/skills/daily-run/SKILL.md`, scan step**
   - When vidIQ is under its floor, an LC fallback: `keyword_posts` (TikTok and Instagram, interval 1w) for the
     character's theme. File only P3-passing posts with engagements ÷ followers as the proxy, and say so on the card.
   - One `keyword_time_series` per trend for P5.
   - The read-only LC tools would need adding to the allow list (owner).
6. **Daily-run caption and first-comment step**
   - C1's 30-character title; C2's fifth hashtag; F1's vote comment.
   - For a `text_led` trend, 2-3 `text_pop` lines in the master spec (P8).
7. **`FOUNDER_CONTEXT.md` / `viral-hook-creator`**
   - Already points here. Section 4.3 is written to be read as-is: the rules, the patterns and the examples.
8. **Weekly review**
   - Store and compare `days_since_trend_peak` (P5), `hook_pattern` (4.3 names), `caption_first_line_pattern` (C3),
     `seamless_loop` (T3) and series vs one-off (4.7).
   - Judge at 72 h and 7 d (4.8). The binding bars stay as they are.

---

## Sources

**Social data (LunarCrush MCP, limited mode, 7 Oct 2026, 25 calls):**
- `keyword_posts`: "dog dance" (TikTok, IG), "dachshund" (TikTok), "dance challenge" (TikTok, 1w), "dance trend" (IG),
  "deadpan" (TikTok), "gangnam style" (TikTok, 1w).
- `keyword_time_series`: "hot dog dance", "ramalama", "gangnam style", "single ladies".
- `post`: TikTok 7692606728323583246 and 7690745166033997086.
- Failed or empty: "boss", "butler" ×2, "ai character", "on the phone", "office", "ai dance", "corporate",
  "charactercomedy", "unbothered", "my boss", "dog costume".

**vidIQ:**
- 0 credits spent; balance 3 before, plan refill 4 Nov.
- Free calls: `vidiq_balance`, `vidiq_jobs_list`, `vidiq_bookmarks_list`, and `vidiq_job_poll` ×7 (watch jobs from 4 Oct:
  DbdfIyOo_cf, 7690387697302654229, DbgmnsDqmn9, 7670256132455238933, DdrNhWfhcKc, Dcy3lrFogZ1, DbdzDK2TeKD).
- The 4 Oct outlier data is quoted from `docs/research/2026-10-04-niche-playbook.md`.

**Web:**
- NewEngen, October 2026 TikTok trends (30 Sep, updated 5 Oct): https://newengen.com/insights/october-tiktok-trends/
- NewEngen, Instagram Reels trends (updated 1 Oct 2026): https://newengen.com/insights/instagram-trends/
- NewEngen, September 2026 TikTok trends (updated 21 Sep): https://newengen.com/insights/september-tiktok-trends
- SocialPilot, TikTok trends (updated 5 Oct 2026): https://www.socialpilot.co/blog/tiktok-trends
- Anijam, Instagram Reels trends 2026 (27 Jul 2026): https://www.anijam.ai/blog/instagram-reels-trends/
- mean.ceo, Instagram trends October 2026: https://blog.mean.ceo/?p=10941
- Metricool, Reel analytics, retention and skip rate (Feb 2026): https://metricool.com/instagram-reel-analytics/
- TrueFutureMedia, lower your Reels skip rate: https://www.truefuturemedia.com/articles/lower-instagram-reels-skip-rate
- inro, Instagram Reels insights 2026: https://www.inro.social/blog/instagram-reels-insights
- socialcrawl, how Instagram counts views (425 posts): https://www.socialcrawl.dev/blog/how-instagram-counts-views
- Chartlex, trending audio and the Reels algorithm (23 Jul 2026): https://www.chartlex.com/blog/marketing/trending-audio-instagram-reels-algorithm-2026
- ttcalculator, TikTok completion rate by length: https://ttcalculator.net/data/engagement/completion-rate-by-video-length/
- Skeepers, writing text hooks: https://community.skeepers.io/blog/writing-text-hooks/
- ClipSpeed, video hook ideas: https://www.clipspeed.ai/blog/video-hook-ideas
- Know Your Meme, Nia Noir: https://amp.knowyourmeme.com/memes/people/nia-noir-nianoirxo
- El Comercio, Gangnam Style in Spanish: https://www.elcomercio.com/tendencias/musica/gangnam-style-traduccion-redes/
- PetsRadar, dogs in ghost costumes (undated, not used for a rule): https://www.petsradar.com/news/dogs-in-ghost-costumes-is-the-only-pet-trend-you-need-to-know-about-this-halloween
