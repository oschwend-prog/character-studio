# Character prompt kit

The studio's own templates for designing and generating characters. Every new character, and every remake, starts here.
They are based on prompt formats the owner shared on 2026-10-08 and rewritten for ODD EYES. Where anything here differs
from `CLAUDE.md` or `docs/AI_INFLUENCERS.md`, those win.

## 0. Studio rules for every prompt
- **The signature.** The character's RIGHT eye (viewer's left) is ice-blue and his LEFT eye (viewer's right) is amber.
  - It is always in the Face line.
  - The negative prompt always carries `matching eye colours`, so the model doesn't drift back to two matching eyes.
- **No brands.** Describe the object ("a gold dress watch"), never name the maker.
- **No real person.** Never "looks like" a celebrity or a creator.
- **Describe skin and features plainly; they are never the joke.** No nationality stereotypes. The Borat-type comes from
  an invented country.
- **The tone:** deadpan and dorky, never mean. The joke is how seriously he takes himself.
- **Franz is a dog.** Since 2026-10-07 he is tall and upright, with a human-like body. Use his canon description and the
  dog guard (anatomy, paws, snout) from `characters/franz/bible.md` instead of the human build and age line.
- **Where:** stills are made with `gpt_image` in Higgsfield (about 2.75 credits each), with the character's references
  attached. The results go to the refs.json slots `masters`, `sheets` and `closeup`.

## 1. How a character is designed
1. Three concepts first, each with:
   - a name;
   - a one-line vibe;
   - the hair, face, outfit and one prop;
   - one signature move or running bit for videos.
2. The owner picks one. Then the full-body still (section 2).
3. Changes are edits of that still (section 4), never a fresh prompt, so the face survives.
4. When the look is right, the character sheet (section 5) and the close-up.
5. Every prompt goes out with its negative prompt (section 3).

What makes a character read at thumbnail size:
- one exaggerated hairstyle;
- one standout facial feature;
- an earnest, slightly old-fashioned outfit worn with total sincerity;
- a straight face.

## 2. Full-body still
```text
Photorealistic full-body studio photograph of [BUILD, AGE AND POSTURE: e.g. a tall, narrow-shouldered man in his sixties
standing ramrod straight], arms [ARMS], looking straight into the camera. Seamless light-grey paper backdrop, even light,
a soft shadow on the floor.
Hair: [THE ONE SIGNATURE STYLE], [COLOUR], groomed to an almost unreasonable precision.
Face: [FACIAL HAIR]; [GLASSES, IF ANY]; [FEATURES]; heterochromia: his right eye (viewer's left) ice-blue, his left eye
(viewer's right) warm amber; a completely straight face, [THE ONE EXPRESSION DETAIL].
Outfit: [EVERY GARMENT WITH COLOUR, FABRIC AND FIT], [SHOES], [THE ONE PROP].
Camera and light: full-frame, 85mm, f/8, eye level, the whole body from head to toe with a margin. Large softbox key
from the front left, gentle fill, a thin rim light. Real skin texture and pores, single hair strands, visible weave in
the fabric, natural creases, true colour, sharp throughout, editorial quality.
```

## 3. Negative prompt
```text
illustration, cartoon, anime, 3D render, CGI look, plastic or waxy skin, airbrushed, doll face, smiling, toothy grin,
deformed hands, extra fingers, warped face, crossed eyes, matching eye colours, blur, low resolution, oversaturated colour,
hard shadows, cluttered background, cropped head, cropped feet, text, captions, watermark, logo, brand names
```
Per character, add what stops his key features drifting, e.g. Reginald: `messy hair, casual clothes`; Lenny:
`pale skin, small watch`.

## 4. Edit prompt (one change at a time)
```text
Use the attached image as the exact reference. Keep the same person, face, eyes, hair, facial hair, glasses, outfit,
pose, light, backdrop and framing. Change only this: [THE ONE CHANGE]. Leave everything else exactly as it is.
```

## 5. Character sheet
```text
A character reference sheet of the same person as in the attached image, identical in every panel: face, eyes, skin,
body, hair, facial hair, glasses and outfit. Photorealistic, seamless light-grey backdrop and the same soft light in
every panel. One wide image in two rows, separated by thin white lines, with no text or labels.
Row 1, five full-length views at the same scale, standing relaxed, arms down: front; three-quarter front; profile;
three-quarter back; back.
Row 2, three chest-up close-ups: front, straight face, eyes open to the lens (the odd eyes clearly visible);
three-quarter, straight face; front, his one signature expression.
CHARACTER: [the full description from the full-body still: build, age, skin, hair, face and eyes, every garment, the
prop].
Full-frame, 85mm, sharp in every panel, real skin and fabric texture, consistent colour across panels.
```
The first close-up (front, eyes open) is the refs.json `closeup` when it is sharp.

## 6. Swap prompt (Genjutsu Object swap)
`studio.drop.swap_prompt` builds it. It says:
- who is replaced, and by which character from the reference images;
- his part (cameo, featured or star);
- his gadgets;
- his performance line.

It also says: use the references for the character only, and keep the original's camera movement, framing, light and
colour grade. For the `star` part the motion line stays ours: he performs every beat with full energy, to beat the
original.

## 7. Picking the clip
These are the free check's score and the hit rules in `config/hit_rules.md`, in short:
- under 30 seconds;
- one clear performer;
- big, readable motion;
- a format people already know;
- a funny contrast with the character.

Ask: is it funnier with him in it?

## 8. Account rules
- The AI label goes on every post, on every platform.
- Original characters only.
- Add a joke, not just a face.
- No private people's personal moments. A child may appear in a clip, but never as the star we replace (2026-10-06),
  and nothing sexualised.
- Dorky, never mean.

Money and distribution (cross-posting, Higgsfield Earn, brand deals) are covered in
`docs/research/2026-10-08-tools-data-earn.md` and `docs/roadmap.md`. Earn pays per approved campaign video, at
confidential rates. Drop-ins on other people's clips are never submitted to it.
