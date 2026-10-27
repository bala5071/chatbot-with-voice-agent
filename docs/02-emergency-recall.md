# 02: Emergency detection, recall first

**Decided:** the emergency check in `safety.py` favours recall over precision.

**Why.** The two mistakes do not cost the same. A false alarm costs the caller one scripted
sentence ("If this is an emergency, hang up and call 911 now.") and a repeated request. A missed
emergency sends the turn to a small model as an ordinary request. So when in doubt, the check
triggers.

**How.**

- **Normalization forgives how a transcript is spelled.**
  - Text is lower-cased and apostrophes are dropped, both straight and curly, so `can't`, `cant`
    and `can't` written with a curly apostrophe are the same word.
  - `9-1-1`, `9 1 1`, `9.1.1` and `9/11` become `911`.
  - A colon is not a separator, so a time like `9:11` stays a time. A street number like `9110`
    is not touched.
- **Fixed phrases** (`EMERGENCY_PHRASES`) are matched as whole words, written in their
  normalized form.
- **Wording families** (`EMERGENCY_FAMILIES`) catch what a flat list would miss:
  - not being able to breathe: a blocking word, up to two words, then `breathe`, `breath` or
    `breathing`, as in "can barely breathe" or "could not catch his breath";
  - chest pain: "chest really hurts", "pressure in my chest";
  - any bleeding;
  - too many pills.

**What must not trigger.** These are tested: ordinary requests ("Can I bring my breathing test
results?", "I need to reschedule my chest x-ray.", "Can I have the 9:11 slot on Tuesday?",
"chestnut street parking", a phone number, a street number).

**Accepted false alarms.** "My daughter is bleeding" triggers even when the caller wants an
appointment for it.

**Known gap.** A mis-transcribed emergency is not caught: the check reads the transcript, not
the audio. `docs/threat-model.md` records this gap. Nothing here measures how often Whisper
mishears an emergency phrase; no such number is claimed.
