"""Build assets/characters/<slug>/spec.png: one-page character spec sheets (white, phone-legible, 1080 wide).

Run from the repo root: ``uv run python assets/characters/build_specs.py``. It reads the reduced copies next to it
(<slug>/turnaround.jpg, expressions.jpg, master.jpg, closeup.jpg, avatar.png); replace those files and re-run to refresh a spec.
The text mirrors characters/<slug>/bible.md (the bible wins if they differ). macOS system fonts (Didot, Avenir Next).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
W, M = 1080, 48
CW = W - 2 * M
DIDOT = "/System/Library/Fonts/Supplemental/Didot.ttc"
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
INK, GREY, RULE = (24, 24, 28), (92, 92, 100), (226, 226, 230)


def avenir(size: int, face: str = "regular") -> ImageFont.FreeTypeFont:
    index = {"bold": 0, "demi": 2, "medium": 5, "regular": 7, "heavy": 8}[face]
    return ImageFont.truetype(AVENIR, size, index=index)


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


class Page:
    def __init__(self, accent: str) -> None:
        self.img = Image.new("RGB", (W, 9000), "white")
        self.d = ImageDraw.Draw(self.img)
        self.y = 0
        self.accent = hex_rgb(accent)

    # -- text ---------------------------------------------------------------------------------------------------
    def runs(self, runs: list[tuple[str, str]], size: int = 30, x0: int = M, width: int = CW, indent: int = 0,
             color=INK, gap: int = 10) -> None:
        """Wrap (text, face) runs inside ``width``; ``indent`` is the hanging indent of the following lines."""
        words: list[tuple[str, ImageFont.FreeTypeFont]] = []
        for text, face in runs:
            fnt = avenir(size, face)
            for i, w in enumerate(text.split(" ")):
                if w:
                    words.append((w, fnt))
        line_h = int(size * 1.32)
        x, first = x0, True
        space = avenir(size).getlength(" ")
        for w, fnt in words:
            wl = fnt.getlength(w)
            limit = x0 + width
            if x + wl > limit and x > x0 + (0 if first else indent):
                self.y += line_h
                x, first = x0 + indent, False
            self.d.text((x, self.y), w, font=fnt, fill=color)
            x += wl + space
        self.y += line_h + gap

    def bullets(self, items: list, size: int = 30) -> None:
        for it in items:
            runs = it if isinstance(it, list) else [(it, "regular")]
            self.d.ellipse((M + 4, self.y + size * 0.5, M + 14, self.y + size * 0.5 + 10), fill=self.accent)
            self.runs(runs, size=size, x0=M + 30, width=CW - 30, gap=6)
        self.y += 6

    def heading(self, text: str, note: str = "") -> None:
        self.y += 18
        self.d.line((M, self.y, W - M, self.y), fill=RULE, width=2)
        self.y += 16
        fnt = avenir(25, "demi")
        x = M
        for ch in text.upper():
            self.d.text((x, self.y), ch, font=fnt, fill=self.accent)
            x += fnt.getlength(ch) + 2.5
        if note:
            self.d.text((x + 12, self.y + 2), note, font=avenir(22, "medium"), fill=GREY)
        self.y += 44

    # -- images -------------------------------------------------------------------------------------------------
    def image(self, path: Path, caption: str, width: int = CW, x: int = M) -> None:
        im = Image.open(path).convert("RGB")
        h = int(im.height * width / im.width)
        self.img.paste(im.resize((width, h), Image.LANCZOS), (x, self.y))
        self.y += h + 10
        self.runs([(caption, "medium")], size=23, color=GREY, gap=14)

    def finish(self, path: Path) -> None:
        self.img.crop((0, 0, W, self.y + M)).save(path, optimize=True)


def build(slug: str, c: dict) -> Path:
    base = HERE / slug
    p = Page(c["accent"])
    p.d.rectangle((0, 0, W, 16), fill=p.accent)
    p.y = 56
    # header: name, avatar, one-liner
    av = Image.open(base / "avatar.png").convert("RGB").resize((168, 168), Image.LANCZOS)
    mask = Image.new("L", (168, 168), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 167, 167), fill=255)
    p.img.paste(av, (W - M - 168, 48), mask)
    p.d.ellipse((W - M - 170, 46, W - M + 2, 218), outline=p.accent, width=4)
    p.d.text((M, p.y), c["name"], font=ImageFont.truetype(DIDOT, 92, index=2), fill=INK)
    p.y += 112
    p.runs([(c["tagline"], "medium")], size=31, width=CW - 200, color=(60, 60, 68), gap=8)
    p.runs([("DESIGNING  ·  AI CHARACTER  ·  ORIGINAL IP  ·  " + c["status"], "demi")], size=20, color=p.accent, gap=8)
    p.y = max(p.y, 236) + 10

    p.heading("Turnaround", c["turn_note"])
    p.image(base / "turnaround.jpg", c["turn_caption"])
    p.heading("Expressions", "readable at thumbnail size")
    p.image(base / "expressions.jpg", c["expr_caption"])

    # master + close-up (the identity references of the swaps), then palette + thumbnail read
    p.heading("Master and close-up", "identity references · ODD EYES")
    top, gap = p.y, 36
    iw = (CW - gap) // 2
    bottom = top
    for i, (name, caption) in enumerate((("master.jpg", c["master_caption"]), ("closeup.jpg", c["closeup_caption"]))):
        im = Image.open(base / name).convert("RGB")
        ih = int(im.height * iw / im.width)
        x = M + i * (iw + gap)
        p.img.paste(im.resize((iw, ih), Image.LANCZOS), (x, top))
        p.d.text((x, top + ih + 8), caption, font=avenir(21, "medium"), fill=GREY)
        bottom = max(bottom, top + ih + 44)
    p.y = bottom
    p.heading("Palette, thumbnail read")
    top = y = p.y
    for name, hx in c["palette"]:
        p.d.rounded_rectangle((M, y, M + 64, y + 64), radius=10, fill=hex_rgb(hx), outline=RULE, width=2)
        p.d.text((M + 84, y + 2), name, font=avenir(27, "demi"), fill=INK)
        p.d.text((M + 84, y + 34), hx.upper(), font=avenir(23, "medium"), fill=GREY)
        y += 80
    x0 = M + iw + gap
    p.y = top
    p.d.text((x0, p.y), "THUMBNAIL READ (50 FT, MUTED)", font=avenir(21, "demi"), fill=p.accent)
    p.y += 34
    p.runs([(c["thumbnail"], "regular")], size=27, x0=x0, width=W - M - x0, gap=6)
    p.y = max(p.y, y + 10)

    p.heading("Signature move", "locked by the owner 2026-10-06")
    p.runs(c["move"], size=30)
    p.heading("Catchphrase", "locked by the owner 2026-10-06")
    p.runs([(c["catchphrase"], "demi")], size=40, gap=4)
    p.runs([(c["catchphrase_alt"], "regular")], size=26, color=GREY)
    p.heading("How he talks")
    p.bullets(c["talks"])
    p.heading("Motion")
    p.bullets(c["motion"])
    p.heading("Wardrobe", "no brand names or logos in prompts")
    p.bullets(c["wardrobe"])
    p.heading("Top 5 props · gadgets", "ready = a Higgsfield asset exists")
    p.bullets(c["props"])
    p.heading("Swap rule")
    p.runs(c["swap"], size=30)
    p.heading("Never")
    p.bullets(c["never"])
    p.heading("Generation")
    p.bullets(c["generation"], size=26)
    out = base / "spec.png"
    p.finish(out)
    return out


R = "regular"
B = "demi"
CHARACTERS = {
    "franz": {
        "name": "Franz", "accent": "#16213B", "status": "VOICE APPROVED",
        "tagline": "The one dachshund: an outraged tiny aristocrat who thinks he is royalty. Permanently unimpressed.",
        "turn_note": "gpt_image_2_5 · a37318e2",
        "turn_caption": "Front · 3/4 · side profile (the extra-long body) · back. The crown in every view; the odd eyes in the front view.",
        "expr_caption": "Full body · haughty chin lift · appalled · smug / panicked · bored · rare delighted (8a9a109e).",
        "master_caption": "Master 806498b8 (odd-eyes edit of 8781919e)",
        "closeup_caption": "Close-up f933609f",
        "palette": [("Polo navy", "#16213B"), ("Cream coat", "#E8D3B4"), ("Pale honey ears", "#D2B697"),
                    ("Crown gold", "#C9A227"), ("Interior beige", "#CDB89C"), ("Right eye, ice-blue", "#8FD3FF"),
                    ("Left eye, amber", "#FFB040")],
        "thumbnail": "An extra-long, low cream sausage silhouette, a dark navy polo block, a flash of gold crown on top, chin in the air.",
        "move": [("The Chin Lift: ", B), ("he stops, raises his nose, turns his head a quarter away and half-closes his eyes. One beat of disdain, then he carries on.", R)],
        "catchphrase": "“That is what people are for.”",
        "catchphrase_alt": "Alternative: “One does not.”",
        "talks": [
            [("Voice: ", B), ("Alistair, preset d9d5c263-f84e-4752-97b5-3750fcc6fd2f (approved by the owner 2026-10-06; model and speech_rate to set).", R)],
            [("Tone: ", B), ("plummy, posh, deadpan. Every sentence a small verdict.", R)],
            "“One does not simply walk. One arrives.”",
            "“Disco? Absolutely not. ...Perhaps one song.”",
            "“I did not run. I relocated, with urgency.”",
            [("Never says: ", B), ("bestie, vibes, slay, hooman, good boy, woof.", R)],
            [("Captions: ", B), ("posh, dry, first person, short full sentences.", R)],
        ],
        "motion": [
            [("Walk: ", B), ("a stiff, dignified gala-trot, chin up. Never rushes.", R)],
            [("Dance: ", B), ("starts above it all, then betrays himself into tiny disco: paw-shuffle, head-bob.", R)],
            [("Provoked: ", B), ("a frantic little-legged scramble, ears flying, then instant composure.", R)],
            [("Can't: ", B), ("stairs. One single step defeats him; he waits to be carried.", R)],
            [("Dog-anatomy guard, every prompt: ", B), ("a real dog's body, long and low, short legs, four paws, no human limbs, dog-sized.", R)],
        ],
        "wardrobe": [
            "Navy fine cotton piqué polo, ribbed knit, soft flat-knit collar, two cream buttons, a side patch pocket with a white contrast stitch, cut long to fit him.",
            "A tiny polished gold crown with round finials, worn tilted. No collar, no shoes, no logos.",
            [("Capsule: ", B), ("tech · athleisure · summer · gala · country weekend.", R)],
        ],
        "props": [
            [("Gold crown ", B), ("(ready, canon): royalty captions, gold at thumbnail size.", R)],
            [("Tortoiseshell sunglasses ", B), ("(ready, be42f42e): lowered slowly on the drop.", R)],
            [("Smartphone ", B), ("(ready, 6012cd3a): left-on-read reactions.", R)],
            [("Over-ear headphones ", B), ("(ready, 57ab3fed): better music than yours.", R)],
            [("Headband + white sneakers ", B), ("(ready, 8f97e211): the aristocrat attempts fitness.", R)],
        ],
        "swap": [("Replaces a DOG star only ", B), ("(like for like). Never a person: a small dog can't replace a human dancer.", R)],
        "never": ["Human limbs, hands or standing like a person; human-sized next to people.",
                  "Logos on the polo; barking, baby talk or slang.",
                  "Climbing a stair successfully.",
                  "The odd eyes swapped or glowing: his RIGHT eye (viewer's left) is ice-blue, his LEFT amber."],
        "generation": ["gpt_image_2_5 · quality high · 2k · reference: master 806498b8 (plus a sheet for a new pose); spell out the odd eyes in every prompt.",
                       "Element a28cc772-0227-4ed1-b6a2-1c84fe3b78f2 for Element models (inside the prompt, never in medias).",
                       "Masters end on the dance: no eye close-up, glint or sting."],
    },
    "reginald": {
        "name": "Reginald", "accent": "#0B3D2E", "status": "NEVER SPEAKS",
        "tagline": "“The Quiff”: a stone-faced head butler and a flawless dancer. The quiff never moves.",
        "turn_note": "gpt_image_2_5 · 44af3625",
        "turn_caption": "Front · 3/4 · side · back. The quiff holds in profile and from behind; tails to the knee.",
        "expr_caption": "Full body · deadpan · raised eyebrow · side-eye / suppressed disapproval · glove-tug stare · single tear (1f02d943).",
        "master_caption": "Master 42772b6a (2K: 4fb61254)",
        "closeup_caption": "Close-up 1afe9ed7",
        "palette": [("Tailcoat black", "#151517"), ("Piqué white", "#F6F6F2"), ("Right eye, ice-blue", "#8FD3FF"),
                    ("Left eye, amber", "#FFB040"), ("Racing green", "#0B3D2E"), ("Gold", "#C9A227")],
        "thumbnail": "A towering black quiff, the tallest thing in any frame, over a round black-and-white silhouette; white gloves flashing; round glasses and a curled moustache up close.",
        "move": [("The Glove Tug: ", B), ("he stops dead, tugs one white glove, then the other, a tiny formal bow, then a deadpan stare down the lens.", R)],
        "catchphrase": "“As you were.”",
        "catchphrase_alt": "Alternative: “The household is unaware.”",
        "talks": [
            [("Never speaks. ", B), ("No voice preset, no voice-over. His lines are gestures and captions.", R)],
            [("Gestures: ", B), ("Glove Tug = “As you were.” · tiny bow = “Very good.” · slow side-eye = “The household is unaware.” · one raised eyebrow = disapproval.", R)],
            "“Kindly do not inform the Duchess.”",
            "“Breakfast will be served at eight. As usual.”",
            [("Never writes: ", B), ("slang, exclamation marks, “dance” in his own sentences.", R)],
        ],
        "motion": [
            [("Walk: ", B), ("a smooth gliding butler's walk, back straight, tray at shoulder height.", R)],
            [("Dance: ", B), ("every trend, perfectly, straight-faced, quiff rigid; then he resumes service mid-beat.", R)],
            [("Provoked: ", B), ("he freezes, a slow side-eye to the lens, then the Glove Tug.", R)],
            [("Can't: ", B), ("smile, speak, rush or spill. The quiff cannot move.", R)],
        ],
        "wardrobe": [
            "Open black barathea tailcoat, satin peak lapels, tails to the knee; a white piqué evening waistcoat; a white marcella shirt with studs; a white piqué bow tie.",
            "Snug white cotton gloves; pressed black trousers; mirror-polished patent oxfords; tiny round black acetate spectacles.",
            [("Capsule: ", B), ("below stairs · cool butler · gym gag · London rain · Halloween.", R)],
        ],
        "props": [
            [("Silver tray + teapot ", B), ("(ready, lookbook da3747f0): “not a drop spilled”.", R)],
            [("Aviators over his glasses ", B), ("(ready): the cool-butler reveal.", R)],
            [("Gold pocket watch ", B), ("(ready): “4pm. Tea.” timing gags.", R)],
            [("Black umbrella ", B), ("(ready): Singin' in the Rain routines, a cane.", R)],
            [("Feather duster ", B), ("(ready): the microphone gag.", R)],
        ],
        "swap": [("Replaces a PERSON star ", B), ("(one clear adult performer, ideally in uniform). Never a dog.", R)],
        "never": ["Smiling or acknowledging the dancing; the quiff moving; speaking.",
                  "A real actor's or famous TV butler's likeness.",
                  "The odd eyes swapped: his RIGHT eye (viewer's left) is ice-blue, his LEFT amber."],
        "generation": ["gpt_image_2_5 · quality high · 2k · reference: master 42772b6a; spell out the odd eyes in every prompt.",
                       "refs.json: master 4fb61254 (2K of 42772b6a) · turnaround 44af3625 · close-up 1afe9ed7.",
                       "Masters end on the dance: no eye close-up, glint or sting."],
    },
    "lenny": {
        "name": "Lenny Gold", "accent": "#5A1A2A", "status": "VOICE LOCKED",
        "tagline": "Manic Hollywood super-agent. Explode in, collapse out. “You're welcome.”",
        "turn_note": "gpt_image_2_5 · 88ac10b9",
        "turn_caption": "Front · 3/4 · side · back. The chalk stripe clear; brown suede loafers; gold watch and ring; the odd eyes in the front view.",
        "expr_caption": "Full body · mid-rant fury · smug calm · fake charm smile / “call my assistant” · shock · “you're welcome” wink (37b754d4).",
        "master_caption": "Master cc6a9f4c (odd-eyes edit of c6864413)",
        "closeup_caption": "Close-up a411c915",
        "palette": [("Suit navy", "#1C2541"), ("Chalk stripe", "#D9D4C7"), ("Tie burgundy", "#5A1A2A"),
                    ("Gold", "#C9A227"), ("Deep tan", "#A86B45"), ("Suede brown", "#4A3426"),
                    ("Right eye, ice-blue", "#8FD3FF"), ("Left eye, amber", "#FFB040")],
        "thumbnail": "A dark power-suit block with very wide shoulders; the phone-to-ear silhouette, elbow up; a white-teeth snarl in a deep-tan face under a black pompadour.",
        "move": [("The Tie Snap: ", B), ("at the collapse he tugs his tie knot, shoots both cuffs and lifts his chin: his template's own gesture.", R)],
        "catchphrase": "“You're welcome.”",
        "catchphrase_alt": "Second line: “Call my assistant.”",
        "talks": [
            [("Voice (locked): ", B), ("Emmett, preset 3c7d32be-0182-5c5e-aa6a-663409bfbb26 · seed_audio · speech_rate 2.", R)],
            [("Tone: ", B), ("fast, loud, staccato, “sweetheart”; then a calm low purr.", R)],
            "“Don't you DARE put me on hold!”",
            "“I don't do ‘maybe’, pal. I do ‘done’.”",
            "“...Eh. Relax. He calls back in five minutes. You're welcome.”",
            [("Never says: ", B), ("sorry, please hold, I'll think about it, or a real person's, agency's or studio's name.", R)],
        ],
        "motion": [
            [("Walk: ", B), ("a power-walk, phone glued to his ear, the free hand chopping the air.", R)],
            [("Template: ", B), ("3 s mid-tantrum call, then he rides the trend, then 2 s of smug calm: Tie Snap and catchphrase.", R)],
            [("Dance: ", B), ("like closing a deal: over-committed, finger-guns on the beat, phone still at his ear.", R)],
            [("Provoked: ", B), ("paces, jabs a finger at the lens, a vein on his temple. ", R), ("Can't: ", B), ("wait, sit still, apologise, hang up first.", R)],
        ],
        "wardrobe": [
            "Navy chalk-stripe wool-silk double-breasted suit, six buttons, wide peak lapels, power shoulders, slim tapered trousers.",
            "White spread-collar shirt, French cuffs, gold cufflinks; burgundy grenadine tie, gold tie bar; white pocket square; dark brown suede loafers.",
            "Gold signet ring; gold watch, cream dial, gold bracelet (a Patek-Philippe-style reference, never named in prompts).",
            [("Capsule: ", B), ("office meltdown · poolside · gala · courtside · golf.", R)],
        ],
        "props": [
            [("Black smartphone ", B), ("(ready): the mid-fight call is the hook.", R)],
            [("Gold watch ", B), ("(ready): tapped at “NOON!”, the deadline gag.", R)],
            [("Gold signet ring ", B), ("(ready): the finger-point, the knuckle-rap.", R)],
            [("Gold tie bar + burgundy tie ", B), ("(ready): the Tie Snap.", R)],
            [("Second phone ", B), ("(idea): two calls at once, one per ear.", R)],
        ],
        "swap": [("Replaces a PERSON star ", B), ("(a suit, a boss, anyone on the phone). Never an animal.", R)],
        "never": ["A real person's likeness or voice: no real agent, actor or TV character.",
                  "The name of a real person, agency or studio; logos on screen.",
                  "Apologising, waiting, hanging up first or ending defeated.",
                  "The odd eyes swapped or glowing: his RIGHT eye (viewer's left) is ice-blue, his LEFT amber."],
        "generation": ["gpt_image_2_5 · quality high · 2k · reference: master cc6a9f4c; spell out the odd eyes in every prompt.",
                       "Soul cdc73565-fa87-47f6-bca4-bb1e7884e483 (soul_2) on file; it flattens expressions toward the snarl.",
                       "Masters end on the dance: no eye close-up, glint or sting."],
    },
}

if __name__ == "__main__":
    for slug, c in CHARACTERS.items():
        print(build(slug, c))
