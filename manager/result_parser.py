"""Parse common status messages printed by existing sync scripts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass
class ParsedOutput:
    new_records: int | None
    message: str
    count_source: str = "unknown"


INSERTED_PATTERNS = [
    re.compile(r"new\s+records?\s+(?:inserted|added|synced)\s*[:=]\s*(\d+)", re.I),
    re.compile(r"records?\s+(?:inserted|added)\s*[:=]\s*(\d+)", re.I),
]
FOUND_PATTERNS = [
    re.compile(r"new\s+records?\s+(?:found|identified|detected)\s*[:=]\s*(\d+)", re.I),
]
TOTAL_TRANSFER_PATTERNS = [
    re.compile(r"total\s+rows?\s+transferred\s*[:=]\s*(\d+)", re.I),
    re.compile(r"total\s+records?\s+transferred\s*[:=]\s*(\d+)", re.I),
    re.compile(r"rows?\s+transferred\s*[:=]\s*(\d+)", re.I),
]
BATCH_TRANSFER_PATTERNS = [
    re.compile(r"transferred\s*:\s*(\d+)\s+rows?", re.I),
    re.compile(r"transferred\s+(\d+)\s+rows?", re.I),
]
NO_NEW_PATTERN = re.compile(
    r"no\s+new\s+records?(?:\s+found)?|no\s+records?\s+to\s+(?:insert|sync)",
    re.I,
)


def _first_count(patterns: list[re.Pattern[str]], lines: list[str]) -> int | None:
    """Return the first matching count, scanning newest output first."""
    for line in reversed(lines):
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                try:
                    return int(match.group(1))
                except (ValueError, IndexError):
                    pass
    return None


def parse_output(output_lines: Iterable[str]) -> ParsedOutput:
    """Extract new-record or transferred-row counts from script output.

    Existing scripts use different print formats. Only report a new-record
    count when output explicitly describes records as new/inserted/found.
    Full-transfer row counts are kept separate to avoid mislabeling them.
    """
    lines = [line.strip() for line in output_lines if line.strip()]

    inserted_count = _first_count(INSERTED_PATTERNS, lines)
    if inserted_count is not None:
        if inserted_count == 0:
            return ParsedOutput(
                new_records=0,
                message="No new records inserted",
                count_source="inserted",
            )
        return ParsedOutput(
            new_records=inserted_count,
            message=f"Inserted {inserted_count:,} new record(s)",
            count_source="inserted",
        )

    found_count = _first_count(FOUND_PATTERNS, lines)
    if found_count is not None:
        if found_count == 0:
            return ParsedOutput(0, "No new records found", "found")
        return ParsedOutput(
            new_records=found_count,
            message=(
                f"Found {found_count:,} new record(s); "
                "insert count was not separately reported"
            ),
            count_source="found",
        )

    if any(NO_NEW_PATTERN.search(line) for line in lines):
        return ParsedOutput(0, "No new records found", "none")

    transfer_count = _first_count(TOTAL_TRANSFER_PATTERNS, lines)
    if transfer_count is None:
        transfer_count = _first_count(BATCH_TRANSFER_PATTERNS, lines)

    if transfer_count is not None:
        return ParsedOutput(
            new_records=None,
            message=(
                f"Transferred {transfer_count:,} row(s); "
                "new-record count not reported by script"
            ),
            count_source="transferred",
        )

    return ParsedOutput(
        new_records=None,
        message="Completed; new-record count not reported by script",
        count_source="unknown",
    )
