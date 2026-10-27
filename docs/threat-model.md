# Threat model

What this demo protects, against what, and the gaps it knows about. It is a demo for synthetic
data and is not HIPAA compliant. Each entry names the code or test that backs it. Entries are
added by the step that changes them.

## Assets

- **The gateway API key** (`GATEWAY_API_KEY`), the only secret the agent holds.
- **What the caller says and hears**: the audio, the transcript, and the reply. In this demo
  they are synthetic, but the code treats them as if they were not.
- **The caller's safety**: an emergency must get the scripted answer, never a generated one,
  and a request for medical advice must not get a generated answer either.

## Threats and what stands against them

| Threat | Defence | Backed by |
|---|---|---|
| The key leaves the machine through a redirect or a proxy | The client follows no redirect and ignores proxy settings from the environment (`trust_env=False`) | `test_redirects_are_not_followed`, `test_the_http_client_ignores_proxy_settings_and_follows_no_redirects` |
| The key goes over plain http, or sits in the URL | Plain `http://` is allowed only to loopback; a URL with credentials, a query or a fragment is refused | `test_refused_gateway_urls` |
| The key ends up in logs, errors, reprs or output | `Secret` redacts its `repr`, `str` and `format`; `reveal()` has one call site; error text holds the type, status and code only | `tests/test_leaks.py` (with a planted control); `test_reveal_is_called_only_where_the_header_is_built` |
| The gateway's message text echoes input back to the caller | The message is never spoken, logged or kept; the caller hears a fixed sentence per error type | `test_status_maps_to_a_spoken_error`, `test_error_inside_the_stream_maps_by_code` |
| Audio or transcripts are stored | Nothing is written unless `--out` is given; `.gitignore` covers audio, transcripts and env files, and a test fails if any is tracked | `test_no_audio_or_text_is_written_without_out`, `tests/test_repo_rules.py` |
| A tampered model download | HTTPS from Hugging Face only, the host checked on every redirect, an exact revision, and every file's hash checked before it is kept | `test_downloads_only_over_https_from_hugging_face`, `test_a_hash_or_size_mismatch_is_refused` |
| A key in a recorded gateway fixture | The recorder refuses to write a fixture containing the key or anything shaped like a key, and a test scans every fixture again | `tests/test_gateway_fixtures.py` (with a planted control) |
| A generated answer to an emergency | `safety.py` checks the transcript before any model call; on a match the caller hears fixed text and the model is never asked | `test_emergency_is_scripted_and_the_model_is_never_called` |
| Medical advice from the model | `safety.py` checks the transcript for dosage, medication, diagnosis and treatment wording before any model call; on a match the caller hears fixed text offering an appointment or a callback, and the model is never asked. The system prompt also forbids advice, which is a second layer, not a guarantee | `test_medical_advice_is_scripted_and_the_model_is_never_called`, `test_the_medical_advice_call_never_reaches_the_model`, `test_medical_advice_requests_are_detected` |

## Known gaps

- **A mis-transcribed emergency is not caught.** The emergency check sees only what Whisper
  wrote, not what the caller said. If speech-to-text drops or garbles the words ("chest pain"
  heard as "just paint", a quiet "can't breathe" heard as nothing), the transcript matches no
  phrase and the turn goes to the model as an ordinary request. Matching is recall-first
  (`docs/02-emergency-recall.md`): it forgives spelling (apostrophes, `9-1-1`) and catches
  wording families. It cannot recover words the transcript does not contain, and nothing here
  has measured how often Whisper `small` mishears them. The caller is never told the check
  exists, so a caller cannot rely on it either.
- **Phrasing the list does not cover is not caught**, in any language other than English
  included. The list and the families are broad but certainly incomplete.
- **False alarms are accepted on purpose.** "My daughter is bleeding" triggers even when the
  caller only wants an appointment. The caller hears one scripted sentence, the model is not
  asked, and the caller has to repeat the request.
- **The medical-advice guard is keyword-based and will miss unusual phrasing.** It matches
  words and a few wording families, not meaning. A request phrased without any of them
  ("Is Calpol okay for a fever?", "Will a hot bath help my back?") goes to the model, and
  then the system prompt is the only safeguard. These misses are listed in
  `tests/test_units.py` (`KNOWN_MISSES`). Like the emergency check, it sees only the
  transcript, so a mis-transcribed request is missed too, and it knows English only.
- **The medicine names are a sample, not a complete list.** `MEDICAL_PHRASES` names some common
  medicines (`ibuprofen`, `tylenol`, `amoxicillin` and a few more). A medicine it does not name,
  asked about without any other trigger word ("Is Calpol okay for a fever?"), goes to the model.
- **Medical-advice false alarms are accepted on purpose.** "Do you treat children?" and a
  prescription refill both get the scripted decline (`KNOWN_FALSE_ALARMS`), even though the
  first is a question about services. The caller hears the decline and an offer of an
  appointment or a callback that is only words (next entry), and has to ask again to reach the
  model.
- **The offer of an appointment or a callback is only words.** The agent books nothing and
  schedules no callback; the caller's next turn goes to the model, which can only take the
  details and say the front desk will call back (`clinic.toml`).
- **A small model can still say something wrong** in an ordinary reply. This is a demo for
  synthetic data, and the README says so.
