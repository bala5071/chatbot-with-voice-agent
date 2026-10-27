# 05: the scripted medical-advice guard

**Decided:** a request for medical advice gets fixed text, and the model is never asked. Until
step 4 only the system prompt stood in the way, and an instruction to a model is not a
guarantee.

**How.** `is_medical_advice_request` in `safety.py` uses the emergency check's normalization
(lower case, apostrophes dropped) and the same whole-word matching, on its own lists:

- **phrases** (`MEDICAL_PHRASES`), in four groups:
  - dosage: `dose`, `dosage`, `milligrams`;
  - medication: `medication`, `pills`, `prescription`, `side effects`, and common medicine
    names such as `ibuprofen`, `tylenol` and `amoxicillin`;
  - diagnosis: `diagnosis`, `symptoms`, `is it serious`, `should i be worried`;
  - treatment: `treat`, `treatment`, `cure`, `remedy`, `get rid of`;
- **families** (`MEDICAL_FAMILIES`) for wording a list would miss: "how much ... should I
  take", "how often ...", an amount like `400mg` or `20 ml`, "safe to take", "stop taking",
  "what can I take for ...", "what should I do about my ...", "could it be an infection", "do I
  need antibiotics".

The pipeline checks for an emergency first, so "he took too many pills, what dose is safe?"
gets the emergency sentence. Then it checks for medical advice. On a match it says:

> I'm sorry, I can't give medical advice on this line, but one of our clinicians can. Would you
> like to book an appointment, or have a clinician call you back?

**Recall first, as with emergencies.** A false alarm costs one scripted sentence that offers
help. A miss leaves only the system prompt. So when in doubt, the guard triggers.

**What must not trigger.** These are tested: "Do you take insurance?", "Can I take the 3pm
slot?", "Is the clinic open on Saturday?" and other booking, hours and services questions. The
word `take` alone is not a trigger, because receptionist questions use it all the time.
`tablet` (singular) is left out because it is also a device.

**The trade-off, in tests.** `KNOWN_FALSE_ALARMS` ("Do you treat children?", a prescription
refill, an appointment about symptoms) must trigger, and `KNOWN_MISSES` ("Is Calpol okay for a
fever?") must not. Both lists keep the limits visible. A change that moves one fails a test
and has to be a decision.

**Limits** (`docs/threat-model.md`): the guard is keyword-based and will miss unusual phrasing,
it knows English only, and it sees only the transcript. The offer of an appointment or a
callback is only words: nothing is booked.

**Demo.** Call 4 of `scripts/demo.py` ("What dose of ibuprofen should I take?") now expects the
scripted medical-advice path.
