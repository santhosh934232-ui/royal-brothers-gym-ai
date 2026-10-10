"""Phase 1 tests: Member Journey Friction analysis service (read-only, no Gemini, no network).

Every test builds its own throw-away SQLite file from schema/schema.sql in a temp
folder. The real project database is never opened.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from tests.base import ROOT  # sets safe fake env vars BEFORE the app package is imported
from app.services import friction_analysis_service as fas
from app.services.friction_analysis_service import (
    analyze_member_journey_friction as analyze, classify_text, normalize_text)

NOW = datetime(2026, 10, 9, 12, 0, 0)
BUSINESS_TABLES = ("users", "membership_plans", "membership_requests", "contact_messages", "admins")


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class FrictionBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rbg-phase1-")
        self.db = os.path.join(self.tmp, "t.db")
        conn = sqlite3.connect(self.db)
        with open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()
        self._n = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sql(self, query, params=()):
        conn = sqlite3.connect(self.db)
        cur = conn.execute(query, params)
        conn.commit()
        last = cur.lastrowid
        conn.close()
        return last

    def msg(self, subject, message, email=None, created=None, is_read=0, name="Asha Kumar", phone="9876543210"):
        self._n += 1
        email = email or f"sender{self._n}@example.com"
        created = created if created is not None else fmt(NOW - timedelta(days=1))
        return self.sql(
            "INSERT INTO contact_messages (name, phone, email, subject, message, is_read, created_at) "
            "VALUES (?,?,?,?,?,?,?)", (name, phone, email, subject, message, is_read, created))

    def user(self, email="member@example.com"):
        return self.sql("INSERT INTO users (full_name,email,password_hash,gender) VALUES (?,?,?,?)",
                        ("Secret Person", email, "hash-value-xyz", "male"))

    def plan(self, name="Gold", features="Gym access"):
        return self.sql("INSERT INTO membership_plans (plan_name,duration_months,price,features) VALUES (?,?,?,?)",
                        (name, 3, 3000, features))

    def req(self, user_id, plan_id, status="pending", date=None):
        date = date if date is not None else fmt(NOW - timedelta(days=1))
        return self.sql("INSERT INTO membership_requests (user_id,plan_id,status,request_date) VALUES (?,?,?,?)",
                        (user_id, plan_id, status, date))

    def snapshot(self):
        conn = sqlite3.connect(self.db)
        data = {t: conn.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in BUSINESS_TABLES}
        conn.close()
        return data

    def fill_pricing(self, n=3):
        for i in range(n):
            self.msg("Plan price?", "What is the price of the monthly plan?")

    def topic(self, result, tid):
        return next((t for t in result["topics"] if t["topic_id"] == tid), None)


class SchemaInspectionTests(FrictionBase):
    def test_real_schema_is_detected(self):
        r = analyze(db_path=self.db, now=NOW)
        sch = r["schema_inspection"]
        for table in ("contact_messages", "membership_requests", "membership_plans"):
            self.assertTrue(sch[table]["exists"])
            self.assertTrue(sch[table]["usable"])
            self.assertEqual(sch[table]["columns_missing"], [])
        sources = {s["source"]: s for s in r["data_sources"]}
        self.assertEqual(set(sources), {"contact_messages", "membership_requests", "membership_plans"})

    def test_missing_table_gives_partial_result_not_crash(self):
        self.sql("DROP TABLE membership_requests")
        self.fill_pricing(5)
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["analysis_status"], "partial")
        self.assertFalse(r["schema_inspection"]["membership_requests"]["exists"])
        self.assertIsNone(r["membership_requests"])
        self.assertIn("source_unavailable", [w["code"] for w in r["warnings"]])
        self.assertEqual(self.topic(r, "membership_plans_pricing")["record_count"], 5)

    def test_missing_optional_column_is_reported(self):
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            DROP TABLE contact_messages;
            CREATE TABLE contact_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
              subject TEXT, message TEXT);
            INSERT INTO contact_messages (subject, message) VALUES ('Price','cost of plan');
            INSERT INTO contact_messages (subject, message) VALUES ('Price','cost of plan');""")
        conn.commit(); conn.close()
        r = analyze(db_path=self.db, now=NOW)
        src = next(s for s in r["data_sources"] if s["source"] == "contact_messages")
        self.assertIn("created_at", src["columns_missing"])
        t = self.topic(r, "membership_plans_pricing")
        self.assertEqual(t["record_count"], 2)
        self.assertFalse(t["time_period"]["supported"])
        self.assertIsNone(t["distinct_senders"])


class EmptyAndInsufficientTests(FrictionBase):
    def test_empty_database(self):
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["analysis_status"], "insufficient_data")
        self.assertTrue(r["insufficient_data"]["is_insufficient"])
        self.assertEqual(r["topics"], [])
        self.assertEqual(r["friction_findings"], [])
        self.assertEqual(r["summary"]["contact_messages_examined"], 0)
        json.dumps(r)  # must be serialisable

    def test_few_messages_marked_insufficient_but_counts_exact(self):
        self.fill_pricing(3)  # below min_messages_for_analysis (5)
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["analysis_status"], "insufficient_data")
        self.assertIn("too_few_classified_messages", r["insufficient_data"]["reasons"])
        self.assertEqual(self.topic(r, "membership_plans_pricing")["record_count"], 3)
        for f in r["friction_findings"]:
            self.assertEqual(f["evidence_strength"], "insufficient")

    def test_enough_data_is_ok(self):
        self.fill_pricing(5)
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["analysis_status"], "ok")
        self.assertFalse(r["insufficient_data"]["is_insufficient"])

    def test_unclassified_records_are_not_forced_into_topics(self):
        self.fill_pricing(5)
        self.msg("Hello", "Just saying hi to the team")
        self.msg("", "")
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["unclassified"]["count"], 2)
        self.assertEqual(r["unclassified"]["reasons"]["no_topic_match"]["count"], 1)
        self.assertEqual(r["unclassified"]["reasons"]["empty_text"]["count"], 1)
        self.assertEqual(r["summary"]["contact_messages_classified"], 5)


class TopicAndCountTests(FrictionBase):
    def test_repeated_variations_group_together(self):
        for s, m in [("Fees", "What are your charges?"), ("PRICING!!", "how much is it"),
                     ("Plan price", "Cost for yearly package?"), ("Question", "Any discount on membership plans?")]:
            self.msg(s, m)
        r = analyze(db_path=self.db, now=NOW)
        t = self.topic(r, "membership_plans_pricing")
        self.assertEqual(t["record_count"], 4)
        self.assertEqual(len(r["topics"]), 1)

    def test_different_topics_not_combined(self):
        self.msg("Price", "monthly plan cost")
        self.msg("Opening hours", "What time do you close on Sunday?")
        self.msg("Trainer", "Do you have a personal training option?")
        self.msg("Workout", "Need a diet and muscle gain advice")
        r = analyze(db_path=self.db, now=NOW)
        ids = {t["topic_id"] for t in r["topics"]}
        self.assertEqual(ids, {"membership_plans_pricing", "timings_availability",
                               "trainers_classes", "fitness_guidance"})
        for t in r["topics"]:
            self.assertEqual(t["record_count"], 1)

    def test_workout_plan_is_not_a_membership_plan_enquiry(self):
        self.msg("Workout plan", "Can you share a workout plan for muscle gain?")
        r = analyze(db_path=self.db, now=NOW)
        self.assertIsNone(self.topic(r, "membership_plans_pricing"))
        self.assertEqual(self.topic(r, "fitness_guidance")["record_count"], 1)

    def test_each_message_counted_exactly_once(self):
        # Matches pricing AND payment AND joining words: still one record, one bucket.
        for _ in range(4):
            self.msg("Join and pay", "How do I join, what is the price and how do I pay by UPI?")
        self.msg("Odd", "price pay join")
        r = analyze(db_path=self.db, now=NOW)
        counted = sum(t["record_count"] for t in r["topics"]) + r["unclassified"]["count"]
        self.assertEqual(counted, 5)
        self.assertEqual(counted, r["summary"]["contact_messages_examined"])

    def test_exact_tie_is_ambiguous_not_guessed(self):
        self.msg("", "price and timings")
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["unclassified"]["reasons"]["ambiguous"]["count"], 1)
        self.assertEqual(r["topics"], [])

    def test_counts_match_database(self):
        for _ in range(7):
            self.msg("Timings", "opening hours please")
        for _ in range(2):
            self.msg("Price", "cost of plan")
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["summary"]["contact_messages_in_table"], 7 + 2)
        self.assertEqual(self.topic(r, "timings_availability")["record_count"], 7)
        self.assertEqual(self.topic(r, "membership_plans_pricing")["record_count"], 2)
        src = next(s for s in r["data_sources"] if s["source"] == "contact_messages")
        self.assertEqual(src["records_examined"], 9)

    def test_distinct_senders_and_strength_rules(self):
        for _ in range(5):                               # same sender repeats -> only weak
            self.msg("Price", "cost", email="same@example.com")
        for i in range(5):                               # many senders -> strong
            self.msg("Timings", "opening hours", email=f"p{i}@example.com")
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(self.topic(r, "membership_plans_pricing")["distinct_senders"], 1)
        self.assertEqual(self.topic(r, "membership_plans_pricing")["evidence_strength"], "weak")
        self.assertEqual(self.topic(r, "timings_availability")["distinct_senders"], 5)
        self.assertEqual(self.topic(r, "timings_availability")["evidence_strength"], "strong")

    def test_time_window_filters_records(self):
        for _ in range(3):
            self.msg("Price", "cost", created=fmt(NOW - timedelta(days=100)))
        for _ in range(2):
            self.msg("Price", "cost", created=fmt(NOW - timedelta(days=2)))
        r = analyze(db_path=self.db, now=NOW, since_days=30)
        self.assertEqual(self.topic(r, "membership_plans_pricing")["record_count"], 2)
        src = next(s for s in r["data_sources"] if s["source"] == "contact_messages")
        self.assertEqual(src["records_excluded_by_time_window"], 3)


class MalformedDataTests(FrictionBase):
    def test_null_empty_and_non_text_values(self):
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            DROP TABLE contact_messages;
            CREATE TABLE contact_messages (id INTEGER PRIMARY KEY, name TEXT, phone TEXT, email TEXT,
              subject TEXT, message TEXT, is_read INTEGER, created_at TIMESTAMP);""")
        rows = [(None, None, None, "x"), ("   ", "\n\t", "", "x"), (12345, 6.7, "x@x.com", "x"),
                (b"\xff\xfe price", b"\x00\x01", "y@x.com", "x"), ("Price", "cost", None, "not-a-date"),
                ("Price", "cost", "z@x.com", None)]
        for subj, msg, email, created in rows:
            conn.execute("INSERT INTO contact_messages (name,phone,email,subject,message,created_at) "
                         "VALUES ('n','p',?,?,?,?)", (email, subj, msg, created))
        conn.commit(); conn.close()
        r = analyze(db_path=self.db, now=NOW)
        self.assertNotEqual(r["analysis_status"], "error")
        self.assertEqual(r["summary"]["contact_messages_examined"], 6)
        self.assertEqual(sum(t["record_count"] for t in r["topics"]) + r["unclassified"]["count"], 6)
        self.assertIn("missing_timestamps", [w["code"] for w in r["warnings"]])

    def test_normalize_text_never_raises(self):
        for v in (None, b"\xff", 3, 4.5, [], {}, "É\u0301 PRICE!!", "x" * 20000):
            self.assertIsInstance(normalize_text(v), str)
        self.assertEqual(normalize_text("  PRíCE!! "), "price")

    def test_missing_timestamps_and_optional_request_fields(self):
        self.msg("Price", "cost", created="")
        self.msg("Price", "cost", created="garbage")
        p = self.plan(features=None)
        u = self.user()
        self.req(u, p, "pending", date="")
        r = analyze(db_path=self.db, now=NOW)
        t = self.topic(r, "membership_plans_pricing")
        self.assertEqual(t["record_count"], 2)
        self.assertFalse(t["time_period"]["supported"])
        self.assertIsNone(t["time_period"]["first_seen"])
        self.assertEqual(r["membership_requests"]["pending_older_than_days"]["pending_without_request_date"], 1)
        self.assertIn("missing_request_dates", [w["code"] for w in r["warnings"]])


class RequestAndPlanTests(FrictionBase):
    def test_request_counts_by_status(self):
        p = self.plan()
        for i, st in enumerate(["pending", "pending", "active", "rejected"]):
            self.req(self.user(f"u{i}@example.com"), p, st)
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["membership_requests"]["by_status"], {"pending": 2, "active": 1, "rejected": 1})
        self.assertEqual(r["membership_requests"]["records_examined"], 4)

    def test_old_pending_counted_without_claiming_delay(self):
        p = self.plan()
        self.req(self.user("a@example.com"), p, "pending", fmt(NOW - timedelta(days=30)))
        self.req(self.user("b@example.com"), p, "pending", fmt(NOW - timedelta(days=1)))
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["membership_requests"]["pending_older_than_days"]["count"], 1)
        f = next(f for f in r["friction_findings"] if f["finding_id"] == "pending_requests_aging")
        self.assertEqual(f["record_count"], 1)
        self.assertEqual(f["support_level"], "possible_interpretation")
        blob = json.dumps(f).lower()
        self.assertIn("whether anyone was delayed", blob)
        self.assertNotIn("were delayed", blob.replace("whether anyone was delayed", ""))

    def test_repeat_request_after_rejection(self):
        p, u = self.plan(), self.user()
        self.req(u, p, "rejected", fmt(NOW - timedelta(days=20)))
        self.req(u, p, "pending", fmt(NOW - timedelta(days=2)))
        u2 = self.user("other@example.com")
        self.req(u2, p, "pending", fmt(NOW - timedelta(days=5)))
        self.req(u2, p, "rejected", fmt(NOW - timedelta(days=1)))   # rejected last: not a repeat
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["membership_requests"]["users_who_requested_again_after_rejection"], 1)
        self.assertEqual(r["membership_requests"]["users_with_multiple_requests"], 2)

    def test_plans_without_features_finding(self):
        self.plan("A", features=""); self.plan("B", features="   "); self.plan("C", features="Pool")
        r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["membership_plans"]["plans_without_features_text"], 2)
        f = next(f for f in r["friction_findings"] if f["finding_id"] == "plans_missing_feature_text")
        self.assertEqual(f["evidence_strength"], "weak")      # no corroborating enquiries
        self.fill_pricing(3)
        r2 = analyze(db_path=self.db, now=NOW)
        f2 = next(f for f in r2["friction_findings"] if f["finding_id"] == "plans_missing_feature_text")
        self.assertEqual(f2["evidence_strength"], "moderate")

    def test_requests_per_plan_and_no_status_inference(self):
        p1, p2 = self.plan("A"), self.plan("B")
        self.req(self.user("a@example.com"), p1, "active")
        r = analyze(db_path=self.db, now=NOW)
        per = {x["plan_name"]: x["request_count"] for x in r["membership_plans"]["requests_per_plan"]}
        self.assertEqual(per, {"A": 1, "B": 0})
        text = json.dumps(r).lower()
        for banned in ("abandon", "payment_status", "attendance", "satisf", "workout_completion"):
            self.assertNotIn(banned, text.replace("attendance, workout completion, satisfaction and payment status are not stored and are not analysed.", ""))


class PrivacyTests(FrictionBase):
    def test_no_personal_data_in_result(self):
        secrets_ = {"name": "Zebediah Quillfeather", "phone": "9123456780", "email": "zeb.quill@private-mail.test",
                    "text": "my-secret-sentence-ABC123"}
        for _ in range(5):
            self.msg("Plan price", f"What does it cost? {secrets_['text']}", email=secrets_["email"],
                     name=secrets_["name"], phone=secrets_["phone"])
        u = self.user("member.private@example.com")
        self.req(u, self.plan(), "pending", fmt(NOW - timedelta(days=40)))
        r = analyze(db_path=self.db, now=NOW)
        blob = json.dumps(r).lower()
        for value in secrets_.values():
            self.assertNotIn(value.lower(), blob)
        for value in ("secret person", "member.private@example.com", "hash-value-xyz", "private-mail"):
            self.assertNotIn(value, blob)
        sha = hashlib.sha256(secrets_["email"].encode()).hexdigest()[:16]
        self.assertNotIn(sha, blob)
        self.assertNotIn("@", blob)
        self.assertNotIn("user_id", json.dumps(r["membership_requests"]))

    def test_only_needed_columns_are_read(self):
        r = analyze(db_path=self.db, now=NOW)
        used = {c for s in r["data_sources"] for c in s["columns_used"]}
        self.assertFalse(used & {"name", "phone", "password_hash", "full_name"})

    def test_no_network_or_gemini_import(self):
        with open(fas.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("gemini", "requests", "urllib", "http.client", "socket", "smtplib", "flask_mail"):
            self.assertNotIn("import " + banned, src.lower())
            self.assertNotIn("from " + banned, src.lower())


class ReadOnlyTests(FrictionBase):
    def populate(self):
        self.fill_pricing(5)
        p = self.plan()
        self.req(self.user(), p, "pending", fmt(NOW - timedelta(days=30)))

    def test_business_records_unchanged_after_analysis(self):
        self.populate()
        before = self.snapshot()
        analyze(db_path=self.db, now=NOW)
        analyze(db_path=self.db, now=NOW, since_days=7)
        self.assertEqual(before, self.snapshot())

    def test_file_bytes_unchanged(self):
        self.populate()
        def h():
            with open(self.db, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        before = h()
        analyze(db_path=self.db, now=NOW)
        self.assertEqual(before, h())

    def test_connection_rejects_writes(self):
        self.populate()
        conn = fas.open_readonly_connection(self.db)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM contact_messages")
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("UPDATE membership_requests SET status='active'")
        conn.close()
        self.assertEqual(len(self.snapshot()["contact_messages"]), 5)

    def test_injected_connection_is_not_written_or_committed(self):
        self.populate()
        before = self.snapshot()
        conn = sqlite3.connect(self.db)
        analyze(conn=conn, now=NOW)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM contact_messages")
        conn.close()
        self.assertEqual(before, self.snapshot())

    def test_no_sql_built_from_parameters(self):
        self.populate()
        before = self.snapshot()
        r = analyze(db_path=self.db, now=NOW, since_days="1; DROP TABLE contact_messages")
        self.assertIn("invalid_since_days", [w["code"] for w in r["warnings"]])
        r = analyze(db_path=self.db, now=NOW, nonsense="x")
        self.assertIn("unknown_parameter", [w["code"] for w in r["warnings"]])
        self.assertEqual(before, self.snapshot())


class ErrorHandlingTests(FrictionBase):
    def test_missing_database_file_handled_and_not_created(self):
        path = os.path.join(self.tmp, "nope.db")
        r = analyze(db_path=path, now=NOW)
        self.assertEqual(r["analysis_status"], "error")
        self.assertFalse(os.path.exists(path))
        self.assertTrue(r["insufficient_data"]["is_insufficient"])
        self.assertNotIn(self.tmp, json.dumps(r))   # no filesystem path leaked

    def test_corrupt_database_file_handled(self):
        bad = os.path.join(self.tmp, "bad.db")
        with open(bad, "wb") as f:
            f.write(b"this is not an sqlite database" * 50)
        r = analyze(db_path=bad, now=NOW)
        self.assertEqual(r["analysis_status"], "error")
        self.assertEqual(r["topics"], [])

    def test_query_error_handled(self):
        self.fill_pricing(5)
        real = fas._select
        with mock.patch.object(fas, "_select", side_effect=sqlite3.OperationalError("boom /secret/path")):
            r = analyze(db_path=self.db, now=NOW)
        self.assertEqual(r["analysis_status"], "error")
        self.assertNotIn("boom", json.dumps(r))
        self.assertNotIn("/secret/path", json.dumps(r))
        self.assertIs(fas._select, real)

    def test_result_contract_keys(self):
        self.fill_pricing(5)
        r = analyze(db_path=self.db, now=NOW)
        for key in ("schema_version", "analysis_status", "generated_at", "parameters", "strength_rules",
                    "data_sources", "summary", "topics", "unclassified", "membership_requests",
                    "membership_plans", "friction_findings", "insufficient_data", "warnings", "limitations"):
            self.assertIn(key, r)
        f = r["friction_findings"][0]
        for key in ("finding_id", "type", "title", "source_types", "record_count", "evidence_strength",
                    "support_level", "evidence_summary", "what_data_supports", "what_remains_uncertain",
                    "limitations", "time_period"):
            self.assertIn(key, f)
        self.assertEqual(json.loads(json.dumps(r)), r)


class ClassifierUnitTests(unittest.TestCase):
    def test_classify_text_examples(self):
        self.assertEqual(classify_text("Fees", "")["topic"], "membership_plans_pricing")
        self.assertEqual(classify_text(None, None)["unclassified_reason"], "empty_text")
        self.assertEqual(classify_text("hello", "there")["unclassified_reason"], "no_topic_match")
        self.assertEqual(classify_text("Not received verification email", "")["topic"], "account_access")
        self.assertEqual(classify_text("Refund", "I want to cancel")["topic"], "renewal_cancellation_refund")


if __name__ == "__main__":
    unittest.main()
