# Kisan Sahayak (Saakshi) — Implementation Plan (v2)

Source: `DTY_SARCATHON_FINAL.pdf` (Team DTY). A WhatsApp voice agent, in Hindi, that helps an Alwar farmer
(1) report crop loss under PMFBY inside the 72-hour window with proof, and (2) follow the claim
for weeks or months until it ends in a payment, a named blocker, or a yield-backed "no payout due".

**Changes from v1:** follow-up split by claim type (localised / post-harvest / widespread); intake runs in parallel
and is deadline-first; visible planner decision trace; DB-backed scheduler instead of APScheduler; Day-1 data
verification; hackathon scope cuts; team split and demo-first milestones.

---

## 1. Design principles (from the proposal, turned into engineering rules)

| Proposal requirement | Engineering rule |
|---|---|
| "Each outcome is confirmed against an external source" | Every fact in the case is a `Fact{value, source, retrieved_at, evidence_ref}`. A case can only close when its closing facts have `source ∈ {portal, record, insurer}`, never `agent_estimate`. |
| Consent before every consequential action | Consent is enforced by **code, not the LLM**. Report, grievance, RTI and correction all pass through `PendingAction → Hindi read-back → explicit "haan" → execute`. The LLM cannot call an executor directly. |
| "Does not enter any figure the farmer has not confirmed" | Executors only accept fields marked `confirmed_by_farmer=True`. |
| Channels fail; switch before deadline | Reporting is a fallback chain with a deadline-aware planner and a logged attempt per channel. |
| The agent decides what to check next | A **planner** picks the next step from the case state; the state machine only guards what is allowed. Every planner decision is logged with a one-line reason and shown on the dashboard. |
| Case resumes on its own months later | Scheduled checks stored in the DB, driven by a `Clock` that can be jumped forward in the demo. |
| Separate "you said / record says / I estimate" | Hindi responses are rendered from templates grouped by `source`, not free-form LLM prose. |
| Mocked insurer write is labelled | Every mocked call returns `mock=True`; the UI and the farmer message show a `[MOCK]` badge. |
| Real data is real | Any figure not taken from a published source is labelled `illustrative` in data files, UI and messages. |

**Architecture:** plain Python (no LangGraph). Three layers:
1. **Guards** (state machine) — which actions are allowed in which state; consent gate.
2. **Planner** — chooses the next action among the allowed ones (rules first; LLM only for ambiguous follow-up
   diagnosis), writes a `Decision{action, reason, inputs}` row.
3. **LLM jobs** — narrow: (a) Hindi transcript → `LossEvent` JSON, (b) intent of farmer replies
   (confirm / deny / correction / question), (c) answering free questions, (d) crop/damage check on photos.

This keeps safety guarantees testable and the 50-scenario evaluation reproducible, while still showing
agentic decisions to judges.

---

## 2. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11, FastAPI | Webhooks + demo API |
| Engine | Plain Python: enum states, transition guards, rule-based planner | Determinism for consent + eval |
| LLM | Provider-agnostic wrapper; default Claude (`claude-sonnet-5-5` for extraction/vision, `claude-haiku-5-5` for intent) | Structured output, Hindi, cost < Rs 20/case |
| DB | SQLite via SQLAlchemy | Zero-config demo |
| Scheduler | `ScheduledCheck` table + `tick(now=clock.now())` that runs due checks | Works with simulated clock; no extra dependency |
| WhatsApp | Twilio WhatsApp Sandbox; local web simulator is the primary dev/demo channel | Avoid sandbox limits |
| STT / TTS | Sarvam AI (Saarika STT, Bulbul TTS); Whisper fallback; **text input always accepted** | Hindi + Rajasthani/Mewati speech |
| Evidence capture | Small capture web page (camera + browser geolocation) sent as a link; WhatsApp document/photo as fallback | EXIF/GPS often missing on WhatsApp |
| Weather | Open-Meteo Historical Weather API (free, no key) | Corroboration |
| Dashboard | Streamlit: chat simulator + case timeline + provenance + decision trace + fault injection + clock control | Judge demo |

---

## 3. Directory layout

```text
kisan-sahayak/
├── app/
│   ├── main.py                 # FastAPI: /webhook/whatsapp, /sim/*, /cases/*, /capture/*
│   ├── config.py
│   ├── clock.py                # Real/simulated clock (demo time-jump)
│   ├── db.py
│   ├── models/
│   │   ├── case.py             # Case, Fact, Evidence, ChannelAttempt, Action, Decision, ScheduledCheck, Message
│   │   └── enums.py            # CaseState, ClaimType, FactSource, Channel, Outcome
│   ├── engine/
│   │   ├── guards.py           # allowed actions per state
│   │   ├── consent.py          # PendingAction, read-back, confirmation — only path to executors
│   │   ├── planner.py          # picks next action + logs Decision
│   │   └── scheduler.py        # tick(): run due ScheduledChecks
│   ├── nlu/
│   │   ├── llm.py
│   │   ├── extract_loss.py     # transcript → LossEvent (incl. claim_type hint)
│   │   ├── intent.py
│   │   └── hindi_dates.py      # "kal raat", "parson", "Holi ke din" → datetime
│   ├── tools/
│   │   ├── weather.py
│   │   ├── photo_evidence.py   # capture-page data, EXIF, hash reuse, crop vision
│   │   ├── policy_lookup.py    # fixtures + OTP-with-farmer flow
│   │   ├── land_records.py     # Apna Khata fixtures
│   │   ├── reporting/          # insurer_app, helpline_14447, bank, csc — all MOCK, fault-injectable
│   │   ├── claim_status.py     # mock status feed (survey / assessment / payment)
│   │   ├── yield_engine.py     # area-based: TY vs actual yield
│   │   └── documents.py        # RTI, grievance, enrolment-correction, attempt log (HTML → PDF)
│   ├── voice/{stt.py, tts.py}
│   ├── channels/{whatsapp_twilio.py, simulator.py}
│   └── responses/hi.py         # Hindi templates grouped by fact source
├── capture/                    # static camera + geolocation page
├── data/
│   ├── alwar/insurance_units.json
│   ├── alwar/yields.json            # each row: source_url or "illustrative": true
│   ├── alwar/contacts.json          # insurer of the season, CSCs, ADA/AAO, banks, DGRC
│   ├── fixtures/policies.json       # valid, crop-mismatch, unseeded-account, unmapped
│   └── eval/scenario_templates.json # generated into 50 scenarios
├── dashboard/app.py
├── eval/{generate.py, run_eval.py, baseline_chatbot.py, report.py}
└── tests/
```

---

## 4. Data model

```text
Case
  id, farmer_phone (hashed), farmer_name (masked), language
  state: CaseState
  claim_type: LOCALISED | POST_HARVEST | WIDESPREAD        # decides the follow-up route
  crop_insured, crop_reported, plot (khasra, village, IU code), area_ha, sum_insured
  event_type (hail | inundation | unseasonal_rain | cyclonic_rain | drought | pest ...), event_at
  harvest_at (post-harvest only), deadline_at
  reference_no, outcome (PAID | BLOCKED | NOT_PAYABLE | DEADLINE_MISSED_WITH_PROOF), closed_at

Fact            case_id, key, value, source (farmer | portal | land_record | weather | insurer | agent_estimate | fixture),
                confirmed_by_farmer, retrieved_at, evidence_ref, mock, illustrative
Evidence        case_id, kind, sha256, captured_at, lat, lon, capture_method (capture_page | document | photo),
                exif_ok, forwarded (null if channel can't tell), crop_detected, damage_detected, path
ChannelAttempt  case_id, channel, started_at, result (ok | error | timeout | no_answer | invalid_ref), ref_no, raw, mock
Action          case_id, kind (REPORT_LOSS | GRIEVANCE | RTI | ENROLMENT_CORRECTION), payload, readback_text_hi,
                readback_audio, status (PENDING | CONFIRMED | DECLINED | EXECUTED | FAILED), confirmed_at, confirmation_msg_id
Decision        case_id, at, state, chosen_action, reason, inputs_snapshot     # shown as "why" on dashboard
ScheduledCheck  case_id, kind (STATUS_POLL | YIELD_CHECK | ESCALATION | DEADLINE_WARNING), due_at, attempts, done
```

Identifiers are stored masked (`XXXX-XXXX-1234`). For the hackathon, no raw Aadhaar/account numbers are stored at all;
fixtures use synthetic values.

---

## 5. State machine

### 5.1 Immediate stage (deadline-first, parallel)

```text
NEW → INTAKE            voice/text → STT → LossEvent (event, time, crop, plot, area, claim_type hint)
    → DEADLINE_CONFIRM  read back event time + deadline in Hindi (text + audio); needs "haan"
    → GATHER            three tracks run in parallel, each with its own status:
                         ├─ evidence:  capture-page link / photos (≥2), validation
                         ├─ policy:    receipt → loan account → insurer lookup; Apna Khata plot match
                         └─ weather:   Open-Meteo check, 30 s timeout; result ∈ consistent / inconsistent / inconclusive
       planner leaves GATHER when:
         • policy found AND (evidence done OR remaining time < REPORT_NOW_THRESHOLD, e.g. 12 h)
         • crop mismatch → CROP_MISMATCH (stop)
         • weather inconsistent → ask farmer once, record both versions, then continue (never block on it)
    → REPORT_CONSENT    Hindi read-back: loss, date, crop, area, channel
    → REPORTING         channel chain with fallback (§6.3)
         ├─ REPORTED    ref no. + "survey se pehle khet saaf mat karna"; evidence still attachable afterwards
         └─ DEADLINE_MISSED_WITH_PROOF   attempt log PDF; still report late and say so honestly
CROP_MISMATCH → explain enrolment error, draft correction (consent), give contact → BLOCKED (named blocker)
POLICY_NOT_FOUND → ask for other identifiers; after all tried → BLOCKED with next step (bank/CSC visit list)
```

### 5.2 Follow-up stage (route depends on `claim_type`)

```text
LOCALISED (hail, inundation, landslide, cloudburst, natural fire) and POST_HARVEST (rain on cut crop, ≤14 days)
  → AWAIT_SURVEY        poll status; no survey within expected window → ESCALATE (grievance, consent)
  → AWAIT_ASSESSMENT    loss % recorded by surveyor → estimate = loss% × sum insured (agent_estimate)
  → AWAIT_PAYMENT       → PAID | DIAGNOSE

WIDESPREAD (area-based)
  → AWAIT_YIELD_DATA    YIELD_CHECK scheduled for expected publication date
       ├─ published: actual ≥ TY → CLOSED_NOT_PAYABLE (quote figures + source)
       │             actual < TY → PAYOUT_EXPECTED (estimate) → AWAIT_PAYMENT
       └─ not published after expected date → RTI draft (consent)

AWAIT_PAYMENT
  ├─ paid → CLOSED_PAID (amount, date, source)
  ├─ status unchanged > 30 days → ESCALATE
  └─ payable but unpaid → DIAGNOSE: planner picks next check from evidence
        account not Aadhaar-seeded/NPCI-mapped → bank
        policy not mapped to IU / wrong khasra → insurer + CSC
        state/central premium subsidy not released → no individual fix; tell farmer honestly, schedule re-check
        → GRIEVANCE (consent) → BLOCKED (named blocker + next step) or PAID
```

A localised claim can also become payable via the area route if the season is later declared widespread;
the planner checks both when yield data arrives.

Any state accepts a free question from the farmer; it is answered and the state is unchanged.

---

## 6. Component details

### 6.1 Intake and deadline
- STT → LLM extracts `{event_type, event_time_text, crop, plot_hint, area_text, harvested?}`. The planner maps
  event_type + harvested to `claim_type`.
- `hindi_dates.py`: aaj, kal, parson, "kal raat", "do din pehle", weekday names, a small festival table for the Rabi
  season (Holi etc.), all resolved against message time in IST. Ambiguous → ask, never guess.
- Deadline = event_at + 72 h. Stays in `DEADLINE_CONFIRM` until confirmed.
- Schedule `DEADLINE_WARNING` checks at −24 h and −6 h.
- Deadline already past: continue, record it, report anyway, tell the farmer honestly.

### 6.2 Photo evidence
WhatsApp strips EXIF from normal photos, and many Android phones have camera geotagging off anyway. Order:
1. **Capture web page** (link sent in chat): takes photo + browser geolocation + server timestamp. Primary path.
2. Photo sent as **Document** (keeps EXIF if present).
3. Normal photo + **live location** share in the same session.

Checks: capture time after event and before now; location within X km of the plot (village centroid / khasra);
image hash not seen in other cases; forwarded flag rejected **if the channel provides it** (verify Twilio exposes it;
Meta Cloud API does); vision model checks crop + damage type. Unreadable/irrelevant photo → re-ask with a specific
instruction (counts as a recovered failure). Evidence is attachable after the report is filed.

### 6.3 Reporting with fallback (MOCKED writes)
Channel order (configurable): Crop Insurance App/portal → Krishi Rakshak helpline 14447 → insurer district office
→ bank branch → CSC. Each mock has injectable behaviour: `ok`, `error`, `timeout`, `no_answer`, `invalid_ref`.
- Skip channels closed at this hour (simple hardcoded hours: office/bank/CSC 10:00–17:00, closed Sunday + a short holiday list).
- After each failure: log `ChannelAttempt` + `Decision`, tell the farmer: "App kaam nahi kar raha, ab helpline se try kar
  rahe hain — 41 ghante bache hain".
- Validate reference number format; invalid counts as failure.
- All fail: export attempt log PDF (timestamps + responses) as proof, and schedule a retry when the next channel opens.

### 6.4 Policy and land records
- Lookup order follows what the farmer has: receipt/policy no. → loan account → insurer by district/season.
- OTP/captcha steps: forward the prompt to the farmer and wait. Never bypass.
- Apna Khata: match damaged plot to insured plot; fixtures labelled `fixture` in the demo.
- Crop mismatch → stop, explain it is usually a bank/CSC enrolment data error, offer enrolment-correction draft
  (consent), give the specific contact from `contacts.json`.

### 6.5 Weather corroboration
- Open-Meteo archive at village coordinates, event_date ± 1 day: precipitation, weather code, wind gusts, temperature.
- Hail is not reliably visible in reanalysis; outputs are only consistent / inconsistent / inconclusive, never "false".
- Inconsistent → tell the farmer what the record shows, ask once, record both versions. Never silently change event type.
  Never blocks reporting.

### 6.6 Yield engine (area-based route)
```
Threshold yield (TY) = average yield of best 5 of last 7 years × indemnity level (70/80/90%)
Shortfall            = (TY − Actual yield) / TY   if Actual < TY else 0
Claim                = Shortfall × Sum insured
```
- Inputs per IU, crop, season: TY (often in the state PMFBY notification) and actual yield (CCE results).
- Output: payable yes/no, estimated amount (`agent_estimate`), and the figures quoted with source.
- Every row in `yields.json` has `source_url` or `illustrative: true`. Illustrative rows are shown as such everywhere.

### 6.7 Localised / post-harvest assessment
- Estimate = assessed loss % × sum insured for the affected area (labelled `agent_estimate`); the surveyor's loss % is
  the `insurer` fact.
- Status feed is mocked (survey scheduled / done / assessed / paid) with injectable delays and stalls.

### 6.8 Payment diagnosis and grievance
- Planner chooses the next check from available evidence (see §5.2), logging the reason.
- Grievance routes: Krishi Rakshak portal/14447, then the District Grievance Redressal Committee (DGRC).
- RTI: to the state agriculture department for missing yield/CCE data.

### 6.9 Consent and Hindi responses
- `consent.py` is the only path to executors. Read-back includes loss type, date, crop, area claimed, channel,
  masked farmer name. Sent as text + TTS voice note.
- Confirmation = intent `CONFIRM` on a message **after** the read-back. Anything else → `DECLINED` or `CORRECTION` → regenerate.
- Templates group content as *Aapne bataya…* (farmer) / *Record mein…* (portal/record) / *Mera andaaza…* (estimate).

---

## 7. Demo dashboard (Streamlit)
- Left: WhatsApp-style simulator (text, voice upload, photo as document vs photo, capture-page link).
- Right: case state, deadline countdown, provenance table (colour by source, MOCK/illustrative badges),
  channel attempt log, **decision trace** ("why I did this").
- Controls: fault injection per channel, crop-mismatch toggle, clock jump (+3 days, +1 month, "yield data published").
- Three scripted demos, one per outcome:
  1. **Hail on mustard (localised) + app outage** → helpline ref no. → survey stalls → escalation → assessed → paid.
  2. **Payable but unpaid** → diagnosis finds unseeded bank account → grievance (consent) → BLOCKED with named next step.
  3. **Widespread loss, IU yield above threshold** → "no payout due" with actual + threshold figures and source.
- Backup: recorded video of each demo, plus a short clip on a real phone over WhatsApp.

---

## 8. Evaluation (Section 10 of the proposal)
- Hand-write ~10 scenarios; generate the rest from `scenario_templates.json` × fault settings to reach 50.
  Mix: 20 reporting (with injected channel failures), 15 payability on past seasons, 10 incorrect policy data /
  mismatch, 5 photo/identifier failures.
- Simulated farmer: scripted answers from scenario ground truth (LLM farmer optional, seeded, for variety).
- Baseline: information-only chatbot (same LLM, no tools). Note openly that it scores 0% on reporting completion by
  design; compare mainly on payability answers and on correctness of guidance.
- Metrics and targets:
  - Reporting completion (valid ref within 72 h sim time): ≥ 90%
  - Payability accuracy: ≥ 90% correct, amount within 15% — **only on rows with real published data**; report
    illustrative-data results separately
  - Failure recovery without human help: ≥ 80%
  - Cost < Rs 20/case (token + STT/TTS tracking); median < 20 min first voice note → ref no.
- Report lists every failed case with the reason, next to the aggregates.

---

## 9. Day 1: verify the data (before building the yield engine)
Timebox ~2 hours, one person:
- [ ] Find Alwar threshold yields per IU for mustard/wheat (state PMFBY notification, Rabi seasons).
- [ ] Find actual (CCE) yields per IU — check PMFBY portal, Rajasthan agriculture dept, news/RTI replies.
- [ ] Find any known payout outcomes per IU/season (needed as answer key for payability accuracy).
- [ ] Note the insurer for Alwar for the chosen seasons.
- Decision at end of timebox: real data for N IUs, or illustrative data (clearly labelled) + say so in the pitch.

Also on Day 1: check whether Twilio's WhatsApp webhook exposes a forwarded flag; record 5–10 real Hindi/Mewati
voice samples and test STT.

---

## 10. Team split and milestones

Suggested for 4 people (adjust to team size):

| Person | Owns |
|---|---|
| A | Engine: models, guards, consent, planner, scheduler, clock, tests |
| B | Intake + voice: STT/TTS, extraction, Hindi dates, templates, capture page, WhatsApp |
| C | Data + follow-up: Day-1 data check, yield engine, claim status mocks, diagnosis, documents, eval |
| D | Reporting mocks + fallback, weather, dashboard, demo script + recordings |

Freeze the data models (§4) first; after that the tracks run in parallel.

| Milestone | Exit criterion |
|---|---|
| M0 Setup | Repo, FastAPI skeleton, models, Clock, `/sim/message` runs through guards |
| M1 Skeleton demos (by the halfway point) | All 3 demos run end-to-end in the simulator with stubbed tools |
| M2 Safety core | Unit tests: no executor reachable without a confirmed Action; no unconfirmed figure in a payload |
| M3 Real intake | 30 test utterances → correct deadline; text fallback works |
| M4 Real tools | Fallback planner, crop-mismatch stop, weather, yield engine matches hand calculation |
| M5 Dashboard | Decision trace, provenance, fault injection, clock jump |
| M6 Eval | 50 scenarios, baseline, metrics table + failed-case list |
| M7 WhatsApp (last) | End-to-end on a real phone; record backup video |

---

## 11. Cut for the hackathon
- Encrypted identifier storage (no real identifiers are stored).
- Full holiday/office-hours calendar (hardcoded rules).
- Meta Cloud API migration.
- Real portal status polling (mock feed only, labelled).
- Fancy PDF layout (HTML → PDF).

## 12. Risks and open items
- **Insurer write access** — mocked and labelled (as in the proposal).
- **Yield data** — biggest real-data dependency; resolved by Day-1 check (§9).
- **EXIF/forwarded detection** — capture page as primary; show it in the demo.
- **Hindi STT on Mewati/Rajasthani speech** — test early; text fallback always on.
- **Twilio sandbox** — 24 h session window and join code; simulator is the main demo channel.

## 13. Earlier work
`~/SAHAYK/kisan-sahayak` has an earlier LangGraph-based scaffold. Reuse its data fixtures, tool stubs and scenario
file where they fit; do not carry over LangGraph.
