# Member Journey Friction Analysis Service (Phase 1)

Module: `app/services/friction_analysis_service.py`
CLI: `python scripts/run_friction_analysis.py [--db FILE] [--since-days N]`
Tests: `python -m unittest tests.test_phase1_friction_analysis -v`

Read-only, no Gemini, no network, no Flask/route/template dependency.

## Usage

```python
from app.services.friction_analysis_service import analyze_member_journey_friction

result = analyze_member_journey_friction()                    # uses Config.DB_PATH, opened mode=ro
result = analyze_member_journey_friction(db_path="x.db", since_days=90)
result = analyze_member_journey_friction(conn=my_sqlite_conn)  # optional injected connection
```

Importing anything under `app` runs `app/config.py`, which (existing project behaviour) requires
`SECRET_KEY`, `MAIL_USERNAME`, `MAIL_PASSWORD` in the environment. The tests set fake values.

The function never raises for database problems; it returns `analysis_status: "error"`.

Optional keyword overrides = keys of `DEFAULT_PARAMETERS` (echoed back in `result["parameters"]`):
`min_messages_for_analysis` (5), `min_messages_per_finding` (2), `moderate_min_messages` (3),
`moderate_min_senders` (2), `strong_min_messages` (5), `strong_min_senders` (3),
`pending_age_days` (7), `since_days` (None), `max_example_ids` (5), `max_text_chars` (5000).
These are analysis RULES, not statistics about the gym.

## Result contract (`schema_version` "1.0")

| Key | Meaning |
|---|---|
| `schema_version` | `"1.0"`. Bump on breaking changes. |
| `analysis_status` | `ok` / `insufficient_data` / `partial` (a source table missing) / `error` |
| `generated_at`, `parameters`, `strength_rules` | When, with which rules, and how strength is decided |
| `schema_inspection` | Per table: `exists`, `usable`, `columns_found`, `columns_missing` |
| `data_sources[]` | `source`, `table`, `available`, `columns_used`, `columns_missing`, `records_examined`, `records_in_table`, `records_excluded_by_time_window`, `records_without_valid_timestamp` |
| `summary` | Contact-message totals (`examined`, `classified`, `unclassified`, `unread`) and overall `time_period` |
| `topics[]` | See below. One entry per detected topic |
| `unclassified` | `count`, `share_of_examined_messages`, `reasons{empty_text,no_topic_match,ambiguous}` each with `count`, `description`, `example_record_ids` |
| `membership_requests` | `by_status{pending,active,rejected}`, `pending_older_than_days{threshold_days,count,pending_without_request_date}`, `users_with_multiple_requests`, `users_who_requested_again_after_rejection`, `requests_per_plan_id`, `time_period` (or `null` if the table is unusable) |
| `membership_plans` | `plans_without_features_text`, `requests_per_plan[{plan_id,plan_name,request_count}]`, `orphan_request_plan_ids` (or `null`) |
| `friction_findings[]` | See below |
| `insufficient_data` | `{is_insufficient: bool, reasons: [..]}` |
| `warnings[]` | `{code, message}`; codes: `source_unavailable`, `missing_timestamps`, `missing_request_dates`, `unknown_request_status`, `high_unclassified_share`, `insufficient_data`, `no_usable_sources`, `analysis_error`, `invalid_since_days`, `unknown_parameter` |
| `limitations[]` | Fixed list of what the data cannot show |

### `topics[]` item
`topic_id`, `label`, `source_type` (`contact_messages`), `record_count`, `share_of_examined_messages`,
`distinct_senders`, `unread_count`, `matched_keywords[{keyword,count}]`,
`time_period{first_seen,last_seen,supported,records_without_timestamp}`,
`evidence_strength` (`insufficient|weak|moderate|strong`), `support_level` (always
`directly_supported_count`), `example_record_ids`, `evidence_summary`.

Topic ids: `membership_plans_pricing`, `membership_request_process`, `payment`,
`renewal_cancellation_refund`, `account_access`, `timings_availability`, `trainers_classes`,
`facilities_equipment`, `location_contact`, `fitness_guidance`, `complaint_feedback`.

### `friction_findings[]` item
`finding_id`, `type` (`repeated_contact_topic`, `pending_membership_requests`,
`repeat_request_after_rejection`, `plan_information_gap`), `title`, `topic_id`, `source_types`,
`record_count`, `distinct_senders`, `time_period`, `evidence_strength`,
`support_level` (`possible_interpretation`), `evidence_summary`, `what_data_supports[]`,
`possible_interpretation`, `what_remains_uncertain[]`, `limitations[]`, `example_record_ids`,
optional `notes[]`.

**Rule for Phase 2:** Gemini may only rephrase, prioritise and recommend from these fields. Counts,
statuses and time ranges must be copied from the result, never recalculated or invented. A finding is
a *possible interpretation*, not a proven problem.

## How classification works
Text is normalised (lower-case, accents stripped, punctuation removed). Subject + message are matched
against keyword rules in `TOPIC_RULES` (subject keywords weigh x2). Each message gets exactly one
primary topic or one unclassified reason, so it is counted once. An exact tie -> `ambiguous`
(not guessed). Workout/diet questions are a separate topic so they are not mixed with membership plans.

## Evidence strength (transparent)
See `result["strength_rules"]`. It measures how much data backs the count (messages + distinct senders),
not whether a problem is proven. If fewer than `min_messages_for_analysis` messages are classified the
whole run is `insufficient_data` and text findings are downgraded to `insufficient` (counts stay exact).

## Privacy
Not returned: names, phones, e-mails, user ids, message text, password hashes. Returned: counts,
matched keywords, plan names, contact-message/request ids, time ranges. E-mail is read only to count
distinct senders, hashed in memory with a random one-off salt.

## Known limitations
English keyword rules only; no reply/resolution tracking; contact messages are not linked to accounts or
plans; no rejection reasons, cancellations, payments, attendance or expiry events in the schema;
admin-deleted requests are invisible.
