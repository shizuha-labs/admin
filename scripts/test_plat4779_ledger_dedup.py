#!/usr/bin/env python3
"""Regression coverage for PLAT-4779's rolling-ledger exact lookup."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("security-ci-to-pulse.py")
SPEC = importlib.util.spec_from_file_location("security_ci_to_pulse", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RollingLedgerDedupTests(unittest.TestCase):
    source_id = "security-ci:shizuha-labs/admin:ledger"

    def test_query_uses_exact_source_id_without_text_search(self) -> None:
        seen_query: dict[str, list[str]] = {}

        def pulse_request(method: str, url: str, token: str, payload=None):
            nonlocal seen_query
            seen_query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            return {"results": []}

        with mock.patch.object(MODULE, "pulse_request", side_effect=pulse_request):
            self.assertIsNone(MODULE.pulse_find_existing("https://pulse.invalid/api", "token", self.source_id))

        self.assertEqual(seen_query["source"], [MODULE.SECURITY_CI_SOURCE])
        self.assertEqual(seen_query["source_id"], [self.source_id])
        self.assertEqual(seen_query["include_archived"], ["true"])
        self.assertNotIn("search", seen_query)

    def test_list_without_source_id_requires_detail_confirmation(self) -> None:
        """Production ItemListSerializer omits source_id — must detail-fetch (P1)."""
        list_row = {
            "id": "canonical-id",
            "item_key": "PLAT-4687",
            "source": MODULE.SECURITY_CI_SOURCE,
            # deliberately no source_id — production list shape
            "status": "blocked",
            "title": "[security-ci] Findings ledger — shizuha-labs/admin",
        }
        detail = {
            **list_row,
            "source_id": self.source_id,
            "description": "Rolling security findings ledger for shizuha-labs/admin.",
            "labels": ["security-ci", "security-ci:ledger"],
        }
        calls: list[str] = []

        def pulse_request(method: str, url: str, token: str, payload=None):
            calls.append(f"{method} {url}")
            if method == "GET" and "/items/?" in url:
                return {"results": [list_row]}
            if method == "GET" and url.endswith("/items/canonical-id/"):
                return detail
            self.fail(f"unexpected {method} {url}")

        with mock.patch.object(MODULE, "pulse_request", side_effect=pulse_request):
            found = MODULE.pulse_find_existing("https://pulse.invalid/api", "token", self.source_id)

        self.assertEqual(found["item_key"], "PLAT-4687")
        self.assertEqual(found["source_id"], self.source_id)
        self.assertEqual(len(calls), 2)
        self.assertIn("/items/canonical-id/", calls[1])

    def test_unverified_list_row_is_not_trusted(self) -> None:
        """Filter drift returning an unrelated row must not yield that row (P1)."""
        foreign = {
            "id": "foreign-id",
            "item_key": "PLAT-9999",
            "source": MODULE.SECURITY_CI_SOURCE,
            # no source_id on list
            "status": "found",
            "title": "some other finding",
        }
        foreign_detail = {
            **foreign,
            "source_id": "security-ci:other-finding",
        }

        def pulse_request(method: str, url: str, token: str, payload=None):
            if method == "GET" and "/items/?" in url:
                return {"results": [foreign]}
            if method == "GET" and url.endswith("/items/foreign-id/"):
                return foreign_detail
            self.fail(f"unexpected {method} {url}")

        with mock.patch.object(MODULE, "pulse_request", side_effect=pulse_request):
            self.assertIsNone(
                MODULE.pulse_find_existing("https://pulse.invalid/api", "token", self.source_id)
            )

    def test_detail_missing_source_id_fails_loud(self) -> None:
        list_row = {"id": "x", "item_key": "PLAT-1", "status": "blocked"}

        def pulse_request(method: str, url: str, token: str, payload=None):
            if "/items/?" in url:
                return {"results": [list_row]}
            return {"id": "x", "item_key": "PLAT-1"}  # detail also omits source_id

        with mock.patch.object(MODULE, "pulse_request", side_effect=pulse_request):
            with self.assertRaises(RuntimeError) as ctx:
                MODULE.pulse_find_existing("https://pulse.invalid/api", "token", self.source_id)
        self.assertIn("fail-loud", str(ctx.exception))

    def test_ambiguous_verified_match_fails_loud(self) -> None:
        rows = [
            {"id": "a", "item_key": "PLAT-A"},
            {"id": "b", "item_key": "PLAT-B"},
        ]

        def pulse_request(method: str, url: str, token: str, payload=None):
            if "/items/?" in url:
                return {"results": rows}
            # both details claim the same source_id
            ref = url.rstrip("/").rsplit("/", 1)[-1]
            return {"id": ref, "item_key": f"PLAT-{ref.upper()}", "source_id": self.source_id}

        with mock.patch.object(MODULE, "pulse_request", side_effect=pulse_request):
            with self.assertRaises(RuntimeError) as ctx:
                MODULE.pulse_find_existing("https://pulse.invalid/api", "token", self.source_id)
        self.assertIn("ambiguous", str(ctx.exception))

    def test_upsert_reuses_canonical_ledger_in_every_status(self) -> None:
        """Production-order: two consecutive upserts per status; list omits source_id."""
        args = argparse.Namespace(
            repo="shizuha-labs/admin",
            ref="refs/heads/main",
            sha="new-scan-sha",
            run_url="https://origin.shizuha.com/shizuha-labs/admin/actions/runs/next",
            project_id=1,
        )

        for status in (
            "found",
            "accepted",
            "in_progress",
            "blocked",
            "awaiting_merge",
            "rejected",
            "completed",
        ):
            with self.subTest(status=status):
                calls: list[tuple[str, str, object]] = []
                # Production list shape: NO source_id (ItemListSerializer).
                list_row = {
                    "id": "canonical-id",
                    "item_key": "PLAT-4687",
                    "source": MODULE.SECURITY_CI_SOURCE,
                    "status": status,
                    "title": "[security-ci] Findings ledger — shizuha-labs/admin",
                    "labels": ["security-ci", "security-ci:ledger"],
                }
                detail = {
                    **list_row,
                    "source_id": self.source_id,
                    "description": "Rolling security findings ledger for shizuha-labs/admin.",
                }

                def pulse_request(method: str, url: str, token: str, payload=None):
                    calls.append((method, url, payload))
                    if method == "GET" and "/items/?" in url:
                        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                        exact = (
                            query.get("source") == [MODULE.SECURITY_CI_SOURCE]
                            and query.get("source_id") == [self.source_id]
                            and query.get("include_archived") == ["true"]
                            and "search" not in query
                        )
                        return {"results": [list_row] if exact else []}
                    if method == "GET" and url.rstrip("/").endswith("/items/canonical-id"):
                        return detail
                    if method == "PATCH":
                        detail["labels"] = payload["labels"]
                        list_row["labels"] = payload["labels"]
                        return detail
                    self.fail(f"unexpected {method} request to {url}")

                with mock.patch.object(MODULE, "pulse_request", side_effect=pulse_request):
                    first_outcome = MODULE.pulse_upsert_ledger("https://pulse.invalid/api", "token", [], args)
                    second_outcome = MODULE.pulse_upsert_ledger("https://pulse.invalid/api", "token", [], args)

                self.assertEqual(first_outcome, "ledger-updated:PLAT-4687")
                self.assertEqual(second_outcome, "ledger-unchanged:PLAT-4687")
                methods = [method for method, _, _ in calls]
                # Each upsert: list GET + detail GET; first also PATCH.
                self.assertEqual(methods, ["GET", "GET", "PATCH", "GET", "GET"])
                self.assertFalse(any(method == "POST" for method, _, _ in calls))


if __name__ == "__main__":
    unittest.main()
