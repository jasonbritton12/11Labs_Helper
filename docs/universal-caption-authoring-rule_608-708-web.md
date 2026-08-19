# Universal Caption Authoring Rule — 608 / 708 / Web

Unless a destination-specific specification requires otherwise, all prerecorded English captions should meet the following house standard:

### Text Density
- **Maximum 32 characters per line**, including spaces, punctuation, speaker identifiers, and sound-effect notation.
- **Maximum 2 lines per caption event.**
- Therefore, treat **64 displayed characters per event as the absolute text-capacity ceiling**, not a target.
- Prefer **one line** whenever the caption reads naturally that way.
- Never allow the renderer to determine important line breaks automatically.

### Reading Speed
- **Target: ≤17 characters per second (CPS).**
- **17–20 CPS: QC warning / acceptable exception** for fast adult dialogue when necessary to preserve meaning or verbatim accessibility.
- **>20 CPS: QC failure** unless specifically approved.
- Do not sacrifice accuracy or meaning merely to hit the CPS target.

### Duration
- **Minimum event duration: 1.0 second.**
- **Maximum event duration: 7.0 seconds.**
- Time captions closely to the associated audio while giving the viewer enough time to read them.
- Do not overlap caption events.
- Where the workflow supports frame-aware timing, maintain clean frame-aligned in/out times and avoid very short unintended gaps.

### Line Breaking
Break lines at natural linguistic boundaries.

Prefer breaks:
- after punctuation;
- between clauses;
- before conjunctions when appropriate;
- at natural speech pauses.

Avoid separating:
- article + noun;
- adjective + noun;
- first + last name;
- subject + verb;
- auxiliary + main verb;
- preposition + its phrase.

Do not create a second line just to hold one or two short words when the caption can be rebalanced naturally.

### Positioning
- Default to **bottom-center**.
- Move captions only when necessary to avoid:
  - important on-screen text;
  - lower thirds;
  - speaker names;
  - scoreboards/tickers;
  - faces or mouths when relevant;
  - other essential visual information.
- Do not depend on precise pixel positioning unless the target format and player require and reliably support it.

### Caption Content
For accessibility/SDH captions, include:
- all meaningful spoken dialogue;
- relevant speaker identification when the speaker is not visually obvious;
- meaningful sound effects;
- music or lyrics when relevant to understanding the program.

Do not caption irrelevant background noise simply because it is audible.

### Characters and Glyphs
- Use a **validated character/glyph set that can survive conversion to CEA-608**.
- Do not assume that every Unicode character supported by WebVTT or IMSC can be represented correctly in 608.
- Validate accented characters, musical symbols, smart punctuation, special symbols, and non-English text during conversion.
- Never silently replace or drop unsupported characters.

### Speaker Changes
- Prefer one speaker per caption event.
- When two speakers must share an event, use **one speaker per line** and clearly identify the change.
- The speaker notation counts toward the 32-character limit.

### Timing and Edit Awareness
- Captions should appear with the associated speech, not noticeably before it.
- Avoid leaving captions hanging significantly after speech has ended.
- Respect shot changes where practical so captions do not visually linger across unrelated edits.
- Caption timing must remain synchronized after frame-rate conversion.

### Delivery Principle
Maintain **one semantic caption master** and transform it into delivery formats rather than independently authoring separate 608, 708, WebVTT, SRT, and TTML files.

Destination-specific requirements always override this house standard.
