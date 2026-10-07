// The scanner's settings as the terminal shows them in "How we scan". config/scan.json is the one place they are written (the
// daily-run skill reads it); this is a copy the bundle can import without reaching outside the app folder, and
// src/lib/analyst.test.ts fails when the two differ. Change a number in scan.json, then here (or regenerate this file).
// The tier rule's numbers are the ones studio/favorites.py TIER_RULES holds too (tests/test_analyst.py pins that side).

export const SCAN_DEFAULTS = {
  "posted_within_days": 14,
  "viewsMin": 200000,
  "outlierScoreMin": 5,
  "durationMax": 30,
  "descriptionLanguage": [
    "en"
  ],
  "collapseByCreator": true,
  "resultsPerPlatform": 20
} as const;

export const SCAN_BUDGET = {
  "vidiq_monthly_credits": 150,
  "scans_per_week": 5,
  "scan_days": [
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri"
  ],
  "breakdowns_per_week": 0,
  "credits_per_scan": 5,
  "credits_per_watch": 10,
  "balance_floor": 5,
  "watches_per_character": 0
} as const;

export const TIER_RULES = {
  "iconic_min_age_days": 180,
  "iconic_min_views": 50000000,
  "viral_now_max_age_days": 21,
  "viral_now_min_outlier": 20,
  "viral_now_min_velocity_per_day": 100000,
  "rising_max_age_days": 7,
  "rising_min_outlier": 5,
  "fallback_viral_now_max_age_days": 30,
  "velocity_min_age_days": 1
} as const;

export const SATURATION_STEPS: ReadonlyArray<{ min_count: number; score: number }> = [
  {
    "min_count": 8,
    "score": 3
  },
  {
    "min_count": 4,
    "score": 5
  },
  {
    "min_count": 1,
    "score": 8
  },
  {
    "min_count": 0,
    "score": 10
  }
];

export const SCAN_ACCESS: ReadonlyArray<{ id: string; name: string; what: string }> = [
  {
    "id": "vidiq_outliers",
    "name": "vidIQ outlier search",
    "what": "Instagram Reels and TikTok, the only places we scan for viral clips: views, how far the video beats its creator's median (the outlier score), and the hook, format and audio analysis. One search each weekday"
  },
  {
    "id": "vidiq_watch",
    "name": "vidIQ watch",
    "what": "A scene-by-scene breakdown of one short video. Not in the daily plan: the free check of an approved clip (people, camera, best window, beat) replaces it"
  },
  {
    "id": "genjutsu",
    "name": "Higgsfield Genjutsu galleries",
    "what": "Trending and New: ready-to-drop-in clips, already clean and trimmed, with previews. Filed only as a backup, on a day the scan could not run or found fewer than 2 usable clips for a character"
  },
  {
    "id": "youtube_stats",
    "name": "YouTube stats",
    "what": "Only the views and dates of iconic moments, to rank them (free)"
  },
  {
    "id": "tiktok_sounds",
    "name": "TikTok trending sounds",
    "what": "What is climbing in the UK and US this week (a sound is never posted without its licence)"
  },
  {
    "id": "owner_links",
    "name": "Your own links",
    "what": "Any TikTok, Instagram Reel or YouTube link you paste, approved on the spot"
  },
  {
    "id": "clip_fetch",
    "name": "Clip fetch",
    "what": "Only for a pick you approved: the public clip is fetched once for the Drop-in, checked here for free, and deleted after posting"
  }
];

export const VIDEO_REQUIREMENTS: ReadonlyArray<string> = [
  "One clear performer or animal as the star",
  "Full body in frame",
  "A mostly static camera",
  "No watermark and no other creator's handle",
  "No text burned into the picture",
  "The star is an adult (children elsewhere in the clip are fine)",
  "People in the background are fine",
  "A clean 6-9 second window to use (16 at most)",
  "Music: the clip's original audio by default"
];

export interface ScanTheme {
  embeddingType: string;
  theme: string;
  query: string;
}
export interface ScanCharacter {
  audienceQuery: string;
  rotation: ReadonlyArray<ScanTheme>;
  fit_rules: ReadonlyArray<string>;
  /** Set while the character is not scanned yet (scan.json `_status`; none of the roster today). */
  status?: string;
}
export const SCAN_CHARACTERS: Readonly<Record<string, ScanCharacter>> = {
  "franz": {
    "audienceQuery": "Culture/Region: UK/US English-speaking; Global: true; Demographics: dog lovers and Gen Z/millennials 16-40 who watch funny pet and dance content;",
    "rotation": [
      {
        "embeddingType": "concept",
        "theme": "dog refuses, then gives in",
        "query": "small dog stubbornly refuses to walk or join in, then gives in to the beat and dances"
      },
      {
        "embeddingType": "hook",
        "theme": "unimpressed dog reaction",
        "query": "small dog stares into the camera, completely unimpressed, while a trend plays around it"
      },
      {
        "embeddingType": "format",
        "theme": "dog does the trend",
        "query": "one small dog doing a viral trend dance or move, full body, static camera, music only"
      },
      {
        "embeddingType": "concept",
        "theme": "show-off dog steals the show",
        "query": "small dog in a cool outfit proudly showing off for the camera, strutting and dancing, one dog on camera"
      }
    ],
    "fit_rules": [
      "one star, a dog or a person; people in the background are fine (other_people is recorded, not a gate); a second dancing star is still filed with needs multi_body and held until the multi-body test passes",
      "a dog or a person as the star (like for like: Franz replaces a dog with his four-paw body, or a person with his upright body; owner 2026-10-07)",
      "full body visible",
      "mostly static camera",
      "music-driven (no dialogue needed)",
      "nothing athletic, no jumping: a dog star moves like a real dog on four paws (the dog-anatomy guard), a person star's dance suits his short-legged upright body",
      "fits Franz's traits card (energy, comedy, moves, settings, props: `bin/studio seed status` > traits): the happiest show-off, bouncy and proud, all-in on the drop, never barks"
    ]
  },
  "reginald": {
    "audienceQuery": "Culture/Region: UK/US English-speaking; Global: true; Demographics: Gen Z and millennials 16-34 who watch comedy, memes and dance trends;",
    "rotation": [
      {
        "embeddingType": "concept",
        "theme": "deadpan at work",
        "query": "stone-faced person in a work uniform performs a trend dance perfectly at work, then calmly resumes the task"
      },
      {
        "embeddingType": "hook",
        "theme": "false premise, then the drop",
        "query": "on-screen premise like 'first day as' then a mundane task done with total seriousness, then the beat drops into a dance"
      },
      {
        "embeddingType": "format",
        "theme": "one action, new location",
        "query": "deadpan costumed character, one repeatable action, changing locations"
      },
      {
        "embeddingType": "concept",
        "theme": "elder out-dances the young",
        "query": "older or formally dressed person steps in and out-dances young people"
      }
    ],
    "fit_rules": [
      "one performer as the star; people in the background are fine (other_people is recorded, not a gate); a second dancing star is still filed with needs multi_body and held until the multi-body test passes",
      "full body visible",
      "deadpan-compatible (the joke must survive a straight face)",
      "no real-person likeness, masks or impersonations as the joke",
      "fits Reginald's traits card (energy, comedy, moves, settings, props: `bin/studio seed status` > traits): calm, deadpan, a straight face under absurdity, never smiling, the quiff never moves"
    ]
  },
  "lenny": {
    "audienceQuery": "Culture/Region: US/UK English-speaking; Global: true; Demographics: Gen Z and millennials 18-40 who watch office comedy, memes and dance trends;",
    "rotation": [
      {
        "embeddingType": "hook",
        "theme": "on hold, then the drop",
        "query": "man in a suit furious on a phone call, then the beat drops and he dances"
      },
      {
        "embeddingType": "concept",
        "theme": "boss vs a mundane problem",
        "query": "boss in a suit reacts to a mundane office problem with total outrage, office comedy skit"
      },
      {
        "embeddingType": "format",
        "theme": "businessman does the trend",
        "query": "one man in a suit does a viral trend dance in an office or a corridor, full body, static camera"
      },
      {
        "embeddingType": "concept",
        "theme": "rage to smug calm",
        "query": "person explodes on the phone, then switches instantly to smug calm, tonal whiplash comedy"
      }
    ],
    "fit_rules": [
      "one performer as the star; people in the background are fine (other_people is recorded, not a gate); a second dancing star is still filed with needs multi_body and held until the multi-body test passes",
      "an adult human star (like for like: Lenny replaces a person, best a man in a suit, a boss or anyone on the phone; never a dog or another animal)",
      "full body visible",
      "the joke survives his template: a mid-tantrum start, then smug calm",
      "no real person's likeness, real agent, agency or studio as the joke",
      "fits Lenny's traits card (energy, comedy, moves, settings, props: `bin/studio seed status` > traits): manic and loud, explode in, collapse out, never waits or apologises"
    ]
  }
};

export const GLOBAL_REJECT_RULES: ReadonlyArray<string> = [
  "a real person's likeness or an impersonation as the joke (the real star is always replaced by our character; a famous clip, meme or dance is fine)",
  "brand ads / sponsored posts",
  "trend more than 7 days past its peak, unless it is an iconic evergreen moment (tier iconic)",
  "already picked or produced",
  "sexualised content, or a child as the star or main subject",
  "national/ethnic/religious stereotypes"
];
