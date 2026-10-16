# Evaluation report

50 scenarios · 50 passed · NLU: rules only · run time 17.3 s

> All policy, yield and weather data used here is **illustrative** (see `data/`). Insurer writes are mocked. Payability ground truth is computed independently in `eval/generate.py` from the same illustrative yield table, so it tests routing, lookup and arithmetic end to end — not agreement with real published payouts.

| Metric | Agent | Info-only baseline | Target |
|---|---|---|---|
| Reporting completion (valid ref ≤ 72 h, faults injected) | 100% (26/26) | 0% (0/26) (cannot file by design) | ≥ 90% |
| Payability accuracy | 100% (19/19) | 0% (0/19) | ≥ 90% |
| Amount within 15% (payable cases) | 100% (9/9) | n/a | — |
| Recovery from injected failures | 100% (31/31) | n/a | ≥ 80% |
| Cost per case | ₹0.0 | — | < ₹20 |
| Median minutes, first message → reference no. (simulated, 3 min per farmer reply) | 15.0 | — | < 20 |

## Failed cases

None.

## All cases

| id | category | final state | ref | estimate ₹ | paid ₹ | pass |
|---|---|---|---|---|---|---|
| S01 | reporting | CLOSED_PAID | CIA-2026-349579 | 13207 | 13207.0 | ✅ |
| S02 | reporting | CLOSED_PAID | KR14447-78195371 | 5465 | 5465.0 | ✅ |
| S03 | reporting | CLOSED_PAID | ALW-IO-75759 | 10019 | 10019.0 | ✅ |
| S04 | reporting | CLOSED_PAID | KR14447-78195371 | 13207 | 13207.0 | ✅ |
| S05 | reporting | CLOSED_PAID | KR14447-69162950 | 4402 | 4402.0 | ✅ |
| S06 | reporting | CLOSED_PAID | CIA-2026-819597 | 16141 | 16141.0 | ✅ |
| S07 | reporting | CLOSED_PAID | CIA-2026-349579 | 16394 | 16394.0 | ✅ |
| S08 | reporting | CLOSED_PAID | KR14447-78195371 | 21859 | 21859.0 | ✅ |
| S09 | reporting | CLOSED_PAID | ALW-IO-75759 | 5465 | 5465.0 | ✅ |
| S10 | reporting | CLOSED_PAID | KR14447-78195371 | 20038 | 20038.0 | ✅ |
| S11 | reporting | CLOSED_PAID | KR14447-69162950 | 5870 | 5870.0 | ✅ |
| S12 | reporting | CLOSED_PAID | CIA-2026-819597 | 14573 | 14573.0 | ✅ |
| S13 | reporting | CLOSED_PAID | CIA-2026-349579 | 16141 | 16141.0 | ✅ |
| S14 | reporting | CLOSED_PAID | KR14447-78195371 | 14573 | 14573.0 | ✅ |
| S15 | reporting | CLOSED_PAID | ALW-IO-75759 | 5465 | 5465.0 | ✅ |
| S16 | reporting | CLOSED_PAID | KR14447-78195371 | 21859 | 21859.0 | ✅ |
| S17 | reporting | CLOSED_PAID | KR14447-69162950 | 11739 | 11739.0 | ✅ |
| S18 | reporting | CLOSED_PAID | CIA-2026-819597 | 20038 | 20038.0 | ✅ |
| S19 | reporting | CLOSED_PAID | CIA-2026-349579 | 4402 | 4402.0 | ✅ |
| S20 | reporting | CLOSED_PAID | KR14447-78195371 | 7286 | 7286.0 | ✅ |
| S21 | payability | CLOSED_PAID |  | 5994 | 5994.0 | ✅ |
| S22 | payability | CLOSED_NOT_PAYABLE |  |  |  | ✅ |
| S23 | payability | CLOSED_NOT_PAYABLE |  |  |  | ✅ |
| S24 | payability | CLOSED_PAID |  | 3943 | 3943.0 | ✅ |
| S25 | payability | CLOSED_NOT_PAYABLE |  |  |  | ✅ |
| S26 | payability | CLOSED_NOT_PAYABLE |  |  |  | ✅ |
| S27 | payability | CLOSED_PAID |  | 6881 | 6881.0 | ✅ |
| S28 | payability | CLOSED_NOT_PAYABLE |  |  |  | ✅ |
| S29 | payability | CLOSED_NOT_PAYABLE |  |  |  | ✅ |
| S30 | payability | CLOSED_PAID |  | 7966 | 7966.0 | ✅ |
| S31 | payability | CLOSED_NOT_PAYABLE |  |  |  | ✅ |
| S32 | payability | CLOSED_NOT_PAYABLE |  |  |  | ✅ |
| S33 | payability | CLOSED_PAID |  | 11122 | 11122.0 | ✅ |
| S34 | payability | CLOSED_NOT_PAYABLE |  |  |  | ✅ |
| S35 | payability | CLOSED_NOT_PAYABLE |  |  |  | ✅ |
| S36 | policy_data | BLOCKED |  |  |  | ✅ |
| S37 | policy_data | BLOCKED |  |  |  | ✅ |
| S38 | policy_data | BLOCKED |  |  |  | ✅ |
| S39 | policy_data | BLOCKED |  |  |  | ✅ |
| S40 | policy_data | BLOCKED |  |  |  | ✅ |
| S41 | policy_data | BLOCKED |  | 3557 |  | ✅ |
| S42 | policy_data | BLOCKED |  | 9937 |  | ✅ |
| S43 | policy_data | BLOCKED |  | 8369 |  | ✅ |
| S44 | policy_data | BLOCKED |  | 8369 |  | ✅ |
| S45 | policy_data | CLOSED_PAID | CIA-2026-349579 | 30056 | 30056.0 | ✅ |
| S46 | photo_identifier | CLOSED_PAID | CIA-2026-349579 | 7286 | 7286.0 | ✅ |
| S47 | photo_identifier | CLOSED_PAID | CIA-2026-349579 | 30056 | 30056.0 | ✅ |
| S48 | photo_identifier | CLOSED_PAID | CIA-2026-349579 | 30056 | 30056.0 | ✅ |
| S49 | photo_identifier | CLOSED_PAID | CIA-2026-349579 | 4402 | 4402.0 | ✅ |
| S50 | photo_identifier | CLOSED_PAID | CIA-2026-349579 | 4402 | 4402.0 | ✅ |
