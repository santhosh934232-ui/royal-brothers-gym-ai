# Friction Insights Service (Phase 2)

Module: `app/services/friction_insights_service.py` · CLI: `python scripts/run_friction_insights.py [--db FILE] [--since-days N]`
Tests: `python -m unittest tests.test_phase2_friction_insights -v` (Gemini fully mocked; no key needed)

```python
from app.services.friction_insights_service import generate_friction_insights
result = generate_friction_insights()                       # runs Phase 1 (read-only), then Gemini if warranted
result = generate_friction_insights(analysis=phase1_dict)   # reuse an existing Phase 1 result
result = generate_friction_insights(db_path="x.db", analysis_overrides={"since_days": 90})
```
**Never raises.** No database writes, e-mails or actions. Uses the existing `gemini_service.generate_text`
(same key/model/timeout config; no second client).

## Flow
1. Get the Phase 1 result (`analyze_member_journey_friction`, schema_version "1.0"; anything else -> `invalid_analysis`).
2. `analysis_status == error` -> status `error` (`analysis_failed`), no Gemini call.
3. Insufficient data (`insufficient_data.is_insufficient` / status `insufficient_data`) -> status `insufficient_data`,
   **no Gemini call**, `additional_data_needed` (derived from Phase 1) and 2 static, labelled general tips.
4. Enough data but no finding with strength weak/moderate/strong -> status `no_findings`, no Gemini call.
5. Otherwise send the evidence (max 8 findings) to Gemini, validate, return insights. Invalid output is retried
   **once** (2 calls max); API/config errors are not retried.

## Result schema (`schema_version` "1.0")
| Key | Meaning |
|---|---|
| `status` | `ok` / `insufficient_data` / `no_findings` / `error` |
| `generated_at`, `disclaimer`, `priority_rule` | UTC time; fixed wording; how priority is set |
| `analysis` | `{schema_version, status, generated_at}` of the Phase 1 run used |
| `verified_facts` | **VERIFIED DATA** copied from Phase 1: `contact_messages{examined,classified,unclassified,time_period}`, `topics[{topic_id,label,record_count,distinct_senders,evidence_strength,time_period}]`, `membership_requests{records_examined,by_status,pending_older_than_days,users_who_requested_again_after_rejection,time_period}` or null, `membership_plans{records_examined,plans_without_features_text}` or null. This exact object is what Gemini sees. |
| `insights[]` | Only when `status == ok`. See below. Sorted high -> low priority |
| `general_suggestions[]` | `{text, scope: "general_not_about_this_gym", ai_generated}`; never a finding |
| `additional_data_needed[]` | Strings (insufficient-data case), deterministic |
| `error` | `null` or `{code, message, http_status}`; message is user-safe |
| `validation` | `{attempts, issues[], findings_offered, insights_accepted, insights_rejected}` (issue codes only) |
| `warnings[]` | `{code, message}`: `no_ai_call_made`, `no_repeated_patterns`, `partial_analysis`, `some_findings_without_insight` |

### `insights[]` item
`finding_id` (a real Phase 1 finding), `title`, `source_types`,
`facts{record_count, distinct_senders, time_period, evidence_summary, what_data_supports}` **(verified, from Phase 1)**,
`interpretation{label, friction_hypothesis, why_it_may_matter, recommendation, supporting_evidence[]}` **(AI, not proven)**,
`priority` (`high|medium|low`), `priority_basis`, `evidence_strength` (`weak|moderate|strong`, from Phase 1),
`limitations[]` (from Phase 1), `information_needed[]` (AI, validated).

Display rule for Phase 3: show `facts` / `verified_facts` as data, and `interpretation` visibly as "AI interpretation".

### Error codes
Gemini (from `gemini_service`): `not_configured`(503), `invalid_key`(502), `rate_limited`(429), `timeout`(504),
`unavailable`(503), `model_unavailable`(502), `bad_request`(502), `empty_response`(502), `unknown`(502).
Service: `invalid_analysis`(500), `analysis_failed`(500), `invalid_ai_output`(502), `unexpected_error`(500).

## What Gemini is asked to return
`{"insights":[{finding_id,title,friction_hypothesis,why_it_may_matter,recommendation,supporting_evidence[],information_needed[]}],"general_suggestions":[...]}`
(optional `record_count` is checked, never used.) Priority/confidence fields from the model are ignored.

## Validation (per insight; failures drop that insight)
Parseable JSON object; `insights` is a list; `finding_id` exists among the findings sent and is not duplicated; required
fields present and strings; stated `record_count` equals Phase 1; every number in any text appears in that finding's
evidence (or message totals); no URLs/code/SQL; no certainty wording ("proven", "definitely"…); no claims about
attendance, satisfaction, churn, abandoned/ignored requests, unanswered messages or payment status (data does not exist);
text clipped to length limits; general tips may contain no numbers. Zero valid insights -> one retry -> `invalid_ai_output`.

## Privacy and prompt injection
Sent: counts, fixed labels, date ranges, fixed rule text written in code. **Not sent:** names, e-mails, phones, user ids,
message text/subjects, matched keywords, plan names, hashes. Because no user-written text reaches the prompt, message
content cannot inject instructions; the system instruction still tells the model to treat `<evidence>` as data only.
Model output is never executed, never used in SQL, and never triggers any action.

## Known limitations
Real Gemini calls are untested here (no key). Validation is strict (numbers/wording), so a real model may occasionally
trigger the retry; tune `_UNSUPPORTED_CLAIM` / prompt after observing real output. Results are not stored or cached
(Phase 3 decision). Analysis quality depends on Phase 1 keyword rules and on how many messages exist.
