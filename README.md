# Kisan Sahayak (Saakshi)

A WhatsApp agent, in Hindi, that helps an Alwar farmer
1. **report a localised crop loss under PMFBY inside the 72-hour window**, with a reference number and geotagged photo evidence, and
2. **follow the claim for weeks or months** until it ends in a payment, a named blocker with the next step, or a yield-backed "no payout due".

Built from `IMPLEMENTATION_PLAN.md` (v2). Team DTY.

---

## What is real, mocked and illustrative

| Part | Status |
|---|---|
| Case state machine, consent gate, planner, scheduler, simulated clock | **Real code**, unit-tested |
| Hindi/Hinglish understanding (dates, event, crop, area, IDs, yes/no) | **Real**: rules always on; Claude used on top when `ANTHROPIC_API_KEY` is set |
| Weather corroboration | **Real API** (Open-Meteo archive); falls back to recorded fixtures if the network call fails |
| PMFBY yield formula (threshold = best 5 of 7 × indemnity) | **Real formula** |
| Yield, threshold and policy figures, IU codes, village coordinates | **Illustrative** — labelled `[उदाहरण डेटा]` / `illustrative` everywhere. Replace after the Day-1 data check |
| Loss intimation to the insurer (app, 14447, office, bank, CSC), claim status, grievance submission | **Mocked**, with fault injection — every message and PDF carries `[MOCK]` |
| Policy lookup, Apna Khata land records | **Fixtures**, behind an OTP step with the farmer in the loop |
| Voice (Sarvam STT/TTS) | Wired, **not tested live** (no key here). Text always works |
| WhatsApp (Twilio) | Wired, **not tested on a real phone** yet. The simulator covers the same flow |

---

## Quick start

```bash
pip install -r requirements.txt
python scripts/make_fixtures.py          # regenerate illustrative data (already committed)

# 1. Judge dashboard (simulator + case internals) — runs everything in-process
streamlit run dashboard/app.py

# 2. API server (WhatsApp webhook, photo capture page, simulator API)
uvicorn app.main:app --reload --port 8000

# Tests and evaluation
pytest -q                                # 74 tests
python eval/generate.py && python eval/run_eval.py   # -> eval/results/report.md
```

No keys are needed to run the demo. Optional keys are listed in `.env.example`.

### Dashboard tour
- **Left:** a WhatsApp-style chat. Type as the farmer in Hindi or Hinglish. You can also send a photo in four ways (capture page / WhatsApp document / WhatsApp photo with EXIF stripped / forwarded), share a live location, or send a voice note.
- **Right:** the case state, deadline countdown, reference number and cost so far, plus these tabs:
  - **Decisions:** the planner's "why" for each step.
  - **Provenance:** every fact, coloured by source.
  - **Channel attempts.**
  - **Consent:** each read-back and its result.
  - **Evidence:** photos and PDFs.
  - **Scheduled checks.**
- **Sidebar:** jump the clock forward (due checks fire in order), inject faults per channel, turn on the crop-mismatch toggle, and run the three scripted demos.

### Three scripted demos (one per outcome)
1. **Hail on mustard + app outage.** The Crop Insurance App fails, the agent switches to helpline 14447 and gets a reference number in about 10 minutes. Press `+3 days` / `+1 month`: survey → 45% loss assessed → estimate → **paid**.
2. **Frost in Kathumar (area-based).** Yield data shows the claim is payable, but the payment fails. The planner checks the **bank first**, because the status says "payment failed". It finds the account is not Aadhaar-seeded, files a grievance with consent, and ends **BLOCKED** with the next step named.
3. **Rain damage in Rajgarh (area-based).** The insurance unit's (IU's) yield is above the threshold, so the agent tells the farmer **"no payout due"** with the actual and threshold figures, and warns them about paying agents.

---

## How it works

```
WhatsApp / simulator / capture page
        │
        ▼
conversation.py ── extract (rules + LLM) ── intent ──┐
        │                                            │ CONFIRM only after a read-back
        ▼                                            ▼
planner.py (state handlers + Decision log) ──► consent.py ──► executors (report, grievance, RTI, correction)
        │                                                     (only path to anything done in the farmer's name)
        ▼
tools/: weather · photo_evidence · policy_lookup · land_records · reporting/channels (MOCK)
        claim_status (MOCK) · yield_engine · diagnosis · documents (PDF)
        │
scheduler.py ── ScheduledCheck table + simulated clock ── follow-up months later
```

**Claim routes** (`nlu/extract_loss.claim_type_for`):
- **Localised** (hail, inundation, lightning fire, cloudburst): 72-hour intimation → survey (10-day SLA, escalate if missed) → assessed loss % → payment.
- **Post-harvest** (rain or hail on a crop already cut and lying in the field): same as localised.
- **Widespread** (frost, drought, pest, rain on a standing crop): no individual intimation. The agent finds the policy, waits for the IU's yield data, then reports payable/not payable with figures. If the data is late, it drafts an RTI.

**Safety guarantees (tested in `tests/test_consent.py`):**
- An executor runs only for an Action that is `CONFIRMED` by a farmer message that came *after* the read-back.
- Every field in the payload must be a farmer-confirmed fact, unchanged since the read-back.
- "No" always beats "yes" (for example, "mat karo" is a no). With the LLM on, CONFIRM needs both the rules and the model to agree.
- A crop mismatch stops filing. The agent offers an enrolment-correction request instead.
- Hindi responses group facts as *आपने बताया* (farmer) / *रिकॉर्ड में* (record) / *मेरा अंदाज़ा* (estimate).

---

## Evaluation (`eval/`)

There are 50 generated scenarios:
- 20 reporting, with channel faults
- 15 payability, on past seasons
- 10 incorrect policy data
- 5 photo or identifier failures

A scripted farmer answers from each scenario's ground truth, and the information-only baseline is scored on the same cases. Latest run, rules-only NLU:

| Metric | Agent | Info-only baseline | Target |
|---|---|---|---|
| Reporting completion (valid ref ≤ 72 h) | 100% (26/26) | 0% (cannot file) | ≥ 90% |
| Payability accuracy | 100% (19/19) | 0% | ≥ 90% |
| Amount within 15% | 100% (9/9) | — | — |
| Recovery from injected failures | 100% (31/31) | — | ≥ 80% |
| Cost per case | ₹0 (LLM off) | — | < ₹20 |
| Median minutes to reference no. | 15 | — | < 20 |

**Read these numbers with care.**
- The scenarios and the farmer simulator were written by the same team that wrote the agent, and the farmer always answers clearly. This shows the pipeline works end to end; it does **not** measure real-world accuracy.
- Payability ground truth comes from the same illustrative yield table.
- Before the final presentation, add messy real utterances (recorded Mewati/Rajasthani speech, typos, mixed scripts) and real published yield data, then re-run. Expect lower numbers, and report the failures.

---

## Day-1 checklist (from the plan)
- [ ] Find Alwar threshold yields and CCE actual yields per IU (state PMFBY notification, Rajasthan agriculture department). Put them in `data/alwar/yields.json` with a `source_url` per row, and set `illustrative: false`.
- [ ] Put the official IU list for the Alwar cluster in `data/alwar/insurance_units.json`.
- [ ] Fill in the season insurer, DGRC and office contacts in `data/alwar/contacts.json`.
- [ ] Record 5–10 real Hindi/Mewati voice notes and test Sarvam STT (`app/voice/stt.py`). Check the endpoint and field names against Sarvam's current docs.
- [ ] Twilio sandbox: join the sandbox, run `ngrok http 8000`, set `PUBLIC_BASE_URL`, and point the sandbox webhook to `POST {PUBLIC_BASE_URL}/webhook/whatsapp`.

## Known gaps / next steps
- Twilio does not report whether an image was forwarded. That check works in the simulator and needs the Meta Cloud API in production.
- `_wa_from` (the raw WhatsApp number) is kept in case flags so follow-ups can be sent. Encrypt it, or move it to a secrets table, before any real pilot.
- A photo that arrives before the policy (and village) is known skips the distance check. It is not re-checked later.
- The claim-status feed is a mock timeline. Real status polling needs portal access with the farmer's OTP.
- "Rain on a standing crop" is routed as area-based. Confirm this against the season's notification.

## Team split (plan §10)
| Person | Files |
|---|---|
| A — engine | `app/engine/*`, `app/models/*`, `app/clock.py`, `tests/test_consent.py` |
| B — intake + voice | `app/nlu/*`, `app/voice/*`, `app/responses/hi.py`, `capture/`, `app/channels/*` |
| C — data + follow-up | `scripts/make_fixtures.py`, `data/`, `app/tools/{yield_engine,claim_status,diagnosis,documents}.py`, `eval/` |
| D — reporting + demo | `app/tools/reporting/*`, `app/tools/weather.py`, `dashboard/app.py`, `app/demo.py` |
