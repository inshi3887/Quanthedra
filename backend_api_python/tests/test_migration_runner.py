"""P1 offline unit tests: discovery, planning and checksum invariants.

These run without PostgreSQL. Database behaviour (advisory lock, ledger,
concurrency) is covered by the integration suite gated on
``TEST_DATABASE_URL``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.migration_runner import (
    MigrationError,
    discover_dated_migrations,
    plan_run,
)


def _make_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    dated = tmp_path / "dated"
    dated.mkdir(exist_ok=True)
    for name, content in files.items():
        (dated / name).write_text(content, encoding="utf-8")
    return tmp_path


def test_discovery_orders_by_version_then_name(tmp_path):
    root = _make_tree(
        tmp_path,
        {
            "20260802_b_second.sql": "SELECT 2;",
            "20260801_a_first.sql": "SELECT 1;",
            "20260801_c_third.sql": "SELECT 3;",
        },
    )
    found = discover_dated_migrations(root)
    assert [m.label for m in found] == [
        "20260801_a_first.sql",
        "20260801_c_third.sql",
        "20260802_b_second.sql",
    ]


def test_discovery_rejects_illegal_filenames(tmp_path):
    root = _make_tree(tmp_path, {"not-a-migration.sql": "SELECT 1;"})
    with pytest.raises(MigrationError, match="Illegal dated-migration filename"):
        discover_dated_migrations(root)


@pytest.mark.parametrize("bad", ["2026010_notenough.sql", "20260101_.sql", "20260101_UPPER-OK.sql"])
def test_discovery_filename_shape_rules(tmp_path, bad):
    root = _make_tree(tmp_path, {bad: "SELECT 1;"})
    if bad == "20260101_UPPER-OK.sql":
        with pytest.raises(MigrationError, match="Illegal"):
            discover_dated_migrations(root)  # hyphen not allowed
    else:
        with pytest.raises(MigrationError, match="Illegal"):
            discover_dated_migrations(root)


def test_discovery_rejects_duplicate_version_name(tmp_path):
    # Non-.sql companion files are still illegal (fail closed, plan P1:
    # "非法文件名、重复版本、缺失文件明确报错") — they must not be silently
    # ignored, otherwise a stray editor backup can hide real drift later.
    root = _make_tree(
        tmp_path,
        {
            "20260101_same.sql": "SELECT 1;",
            "20260101_same.sql.bak": "SELECT 1;",
        },
    )
    with pytest.raises(MigrationError, match="Illegal"):
        discover_dated_migrations(root)

    # True duplicate (case-insensitive name collision) also fails. The
    # directory lives inside tmp_path so pytest gives every run a fresh one.
    dup = tmp_path / "dup_case" / "dated"
    dup.mkdir(parents=True, exist_ok=True)
    (dup / "20260101_Same.sql").write_text("SELECT 1;", encoding="utf-8")
    (dup / "20260101_same.sql").write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(MigrationError, match="Duplicate"):
        discover_dated_migrations(dup.parent)


def test_discovery_requires_directory(tmp_path):
    with pytest.raises(MigrationError, match="missing"):
        discover_dated_migrations(tmp_path / "absent")


def test_plan_run_split_and_checksum_drift(tmp_path):
    root = _make_tree(
        tmp_path,
        {
            "20260101_a.sql": "SELECT 1;",
            "20260102_b.sql": "SELECT 2;",
        },
    )
    files = discover_dated_migrations(root)
    a, b = files

    # Empty ledger: both pending.
    to_apply, applied = plan_run(files, {})
    assert [m.label for m in to_apply] == ["20260101_a.sql", "20260102_b.sql"]
    assert applied == []

    # Both applied with matching checksums: nothing pending.
    ledger = {(m.version, m.name): m.checksum for m in files}
    to_apply, applied = plan_run(files, ledger)
    assert to_apply == []
    assert len(applied) == 2

    # Edited published file -> checksum drift, fail closed.
    (root / "dated" / "20260101_a.sql").write_text("SELECT 111;", encoding="utf-8")
    drifted = discover_dated_migrations(root)
    with pytest.raises(MigrationError, match="Checksum drift"):
        plan_run(drifted, ledger)


def test_plan_run_detects_ledger_row_without_file(tmp_path):
    root = _make_tree(tmp_path, {"20260101_a.sql": "SELECT 1;"})
    files = discover_dated_migrations(root)
    ghost = ("20991231", "ghost")
    with pytest.raises(MigrationError, match="no matching file"):
        plan_run(files, {ghost: "x" * 64})
