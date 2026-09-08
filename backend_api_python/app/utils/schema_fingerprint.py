"""P1: normalised schema manifest + fingerprint for baseline adoption.

The legacy-QD-database baseline rule (plan P1 task 7):

- The reference schema is built by executing ``init.sql`` plus *all* dated
  migrations from the recorded baseline commit against an EMPTY database.
- A manifest covers semantic objects only: extensions, enums, sequences
  (owned), tables (columns with resolved types/defaults/nullability),
  primary keys, foreign keys, unique constraints, check constraints,
  indexes, triggers and functions. Physical noise (OIDs, reltuples,
  storage params, autovacuum settings) is excluded.
- An existing database may be stamped as ``baseline`` ONLY when its
  manifest matches the reference manifest exactly. Any mismatch is
  fail-closed: the command emits a reconciliation report (diff list) for
  human review instead of stamping.
- The migration ledger itself (``qd_schema_migrations``) is excluded so
  the comparison is independent of adoption state.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List

# Ledger is created by the runner itself and must not participate in the
# fingerprint comparison.
EXCLUDED_TABLES = {"qd_schema_migrations"}

EXCLUDED_EXTENSIONS = {"plpgsql"}  # default in every Postgres install


def _rows(cur, sql: str, params: dict | None = None) -> list[dict]:
    cur.execute(sql, params or {})
    out: list[dict] = []
    for r in cur.fetchall() or []:
        if isinstance(r, dict):
            out.append(r)
        else:  # plain tuple cursor: zip with described column names
            out.append({d[0]: v for d, v in zip(cur.description, r)})
    return out


def _table_oid(cur, table: str, schema: str = "public"):
    """Resolve the table OID via to_regclass; cursor-shape agnostic."""
    cur.execute("SELECT to_regclass(%s)::oid AS oid_map", (f"{schema}.{table}",))
    row = cur.fetchone()
    try:
        return row["oid_map"] if row is not None else None
    except (TypeError, KeyError):
        return row[0] if row is not None else None


def collect_manifest(cur, schema: str = "public") -> Dict[str, Any]:
    """Collect a normalised, order-independent manifest of one schema.

    The scratch-schema reference build passes its own schema name; live
    databases use the default ``public``. All catalog filters key off this
    argument — never off search_path — so a reference built in a scratch
    schema and a live public schema are directly comparable.
    """
    manifest: Dict[str, Any] = {}

    def fold(text: str) -> str:
        """Fold search-path noise: the public. prefix (live DBs) and the
        scratch schema prefix (reference builds in p1_reference_schema_scratch)."""
        return _fold_public((text or "").replace(f"{schema}.", ""))

    manifest["extensions"] = sorted(
        r["extname"]
        for r in _rows(cur, "SELECT extname FROM pg_extension")
        if r["extname"] not in EXCLUDED_EXTENSIONS
    )  # extensions are cluster-wide, unaffected by schema

    manifest["enums"] = sorted(
        {"type": r["name"], "labels": r["labels"]} | {"name": r["name"]}
        for r in _rows(
            cur,
            """
            SELECT t.typname AS name,
                   array_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels
            FROM pg_type t
            JOIN pg_enum e ON e.enumtypid = t.oid
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE n.nspname = 'public'
            GROUP BY t.typname
            """,
        )
    )

    sequences = sorted(
        r["sequencename"]
        for r in _rows(
            cur,
            "SELECT sequencename FROM pg_sequences WHERE schemaname = %(schema)s",
            {"schema": schema},
        )
    )
    manifest["sequences"] = sequences

    tables = [
        r["tablename"]
        for r in _rows(
            cur,
            "SELECT tablename FROM pg_tables WHERE schemaname = %(schema)s ORDER BY tablename",
            {"schema": schema},
        )
        if r["tablename"] not in EXCLUDED_TABLES
    ]
    manifest["tables"] = {}
    for table in sorted(tables):
        tinfo: Dict[str, Any] = {}

        columns = _rows(
            cur,
            """
            SELECT a.attname AS name,
                   pg_catalog.format_type(a.atttypid, a.atttypmod) AS type,
                   COALESCE(pg_get_expr(ad.adbin, ad.adrelid), '') AS default_expr,
                   NOT a.attnotnull AS nullable
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
            WHERE n.nspname = %(schema)s
              AND c.relname = %(table)s
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            {"table": table, "schema": schema},
        )
        tinfo["columns"] = [
            {
                "name": c["name"],
                "type": c["type"],
                "nullable": c["nullable"],
                "default": _normalise_default(c["default_expr"]),
            }
            for c in columns
        ]

        tinfo["primary_key"] = [
            r["attname"]
            for r in _rows(
                cur,
                """
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = %(table_oid)s AND i.indisprimary
                ORDER BY a.attnum
                """,
                {"table_oid": _table_oid(cur, table, schema)},
            )
        ]

        fks = _rows(
            cur,
            """
            SELECT conname,
                   pg_get_constraintdef(oid) AS defn
            FROM pg_constraint
            WHERE conrelid = %(table_oid)s AND contype = 'f'
            ORDER BY conname
            """,
            {"table_oid": _table_oid(cur, table, schema)},
        )
        tinfo["foreign_keys"] = [
            {"name": r["conname"], "definition": fold(r["defn"])} for r in fks
        ]

        others = _rows(
            cur,
            """
            SELECT conname, contype, pg_get_constraintdef(oid) AS defn
            FROM pg_constraint
            WHERE conrelid = %(table_oid)s AND contype IN ('u','c')
            ORDER BY conname
            """,
            {"table_oid": _table_oid(cur, table, schema)},
        )
        tinfo["unique_constraints"] = [
            {"name": r["conname"], "definition": r["defn"]} for r in others if r["contype"] == "u"
        ]
        tinfo["check_constraints"] = [
            {"name": r["conname"], "definition": fold(_normalise_check(r["defn"]))}
            for r in others
            if r["contype"] == "c"
        ]

        indexes = _rows(
            cur,
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = %(schema)s AND tablename = %(table)s
            ORDER BY indexname
            """,
            {"table": table, "schema": schema},
        )
        tinfo["indexes"] = [
            {"name": r["indexname"], "definition": fold(_normalise_index(r["indexdef"]))}
            for r in indexes
        ]

        triggers = _rows(
            cur,
            """
            SELECT tgname, pg_get_triggerdef(oid) AS defn
            FROM pg_trigger
            WHERE tgrelid = %(table_oid)s AND NOT tgisinternal
            ORDER BY tgname
            """,
            {"table_oid": _table_oid(cur, table, schema)},
        )
        tinfo["triggers"] = [
            {"name": r["tgname"], "definition": fold(r["defn"])} for r in triggers
        ]

        manifest["tables"][table] = tinfo

    funcs = _rows(
        cur,
        """
        SELECT p.proname AS name,
               pg_catalog.pg_get_function_identity_arguments(p.oid) AS args,
               pg_catalog.pg_get_function_result(p.oid) AS returns
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = %(schema)s
        ORDER BY p.proname, args
        """,
        {"schema": schema},
    )
    manifest["functions"] = sorted(f"{r['name']}({r['args']}) -> {r['returns']}" for r in funcs)

    return manifest


def _fold_public(text: str) -> str:
    """Drop schema qualification (search-path dependent, not semantic)."""
    return re.sub(r"public\.([A-Za-z0-9_]+)", r"\1", text or "")


def _normalise_default(expr: str) -> str:
    """Fold harmless casts/noise so identical semantics compare equal.

    Schema-qualified object names inside defaults (``nextval('public.x_seq'...)``
    vs ``nextval('x_seq'...)``) depend only on the search_path of the session
    that created them — fold to the bare object name so semantically identical
    schemas compare equal.
    """
    expr = (expr or "").strip()
    expr = re.sub(r"'(public\.)?([A-Za-z0-9_]+)'", r"'\2'", expr)
    return expr


def _normalise_check(defn: str) -> str:
    """Postgres versions differ in spacing for CHECK definitions; fold
    schema-qualified names the same way as defaults."""
    text = " ".join((defn or "").replace("(", " ( ").replace(")", " ) ").split())
    return _fold_public(text)


def _normalise_index(indexdef: str) -> str:
    """Index definitions embed the table name in quotes; fold whitespace and
    keep the semantically relevant remainder."""
    text = " ".join((indexdef or "").split())
    # CREATE [UNIQUE] INDEX name ON public.table USING btree (cols) [WHERE ...]
    lowered = text.lower()
    if lowered.startswith("create unique index"):
        text = "CREATE UNIQUE INDEX " + text[len("CREATE UNIQUE INDEX "):]
    elif lowered.startswith("create index"):
        text = "CREATE INDEX " + text[len("CREATE INDEX "):]
    return _fold_public(text)


def manifest_fingerprint(manifest: Dict[str, Any]) -> str:
    payload = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def diff_manifests(current: Dict[str, Any], reference: Dict[str, Any]) -> List[str]:
    """Human-readable diff list (reconciliation report body)."""
    out: List[str] = []
    for ext in sorted(set(current["extensions"]) - set(reference["extensions"])):
        out.append(f"extension-only-in-current: {ext}")
    for ext in sorted(set(reference["extensions"]) - set(current["extensions"])):
        out.append(f"extension-missing-in-current: {ext}")

    cur_tables = set(current["tables"])
    ref_tables = set(reference["tables"])
    for t in sorted(cur_tables - ref_tables):
        out.append(f"table-only-in-current: {t}")
    for t in sorted(ref_tables - cur_tables):
        out.append(f"table-missing-in-current: {t}")
    for t in sorted(cur_tables & ref_tables):
        c, r = current["tables"][t], reference["tables"][t]
        cur_cols = {col["name"]: col for col in c["columns"]}
        ref_cols = {col["name"]: col for col in r["columns"]}
        for name in sorted(set(cur_cols) - set(ref_cols)):
            out.append(f"column-only-in-current: {t}.{name}")
        for name in sorted(set(ref_cols) - set(cur_cols)):
            out.append(f"column-missing-in-current: {t}.{name}")
        for name in sorted(set(cur_cols) & set(ref_cols)):
            if cur_cols[name] != ref_cols[name]:
                out.append(f"column-differs: {t}.{name} current={cur_cols[name]} reference={ref_cols[name]}")
        for key in ("primary_key", "unique_constraints", "check_constraints", "foreign_keys", "triggers"):
            if c[key] != r[key]:
                out.append(f"{key.replace('_', '-')}-differs: {t}")
        cur_idx = {i["name"]: i["definition"] for i in c["indexes"]}
        ref_idx = {i["name"]: i["definition"] for i in r["indexes"]}
        for name in sorted(set(cur_idx) - set(ref_idx)):
            out.append(f"index-only-in-current: {t}.{name}")
        for name in sorted(set(ref_idx) - set(cur_idx)):
            out.append(f"index-missing-in-current: {t}.{name}")
        for name in sorted(set(cur_idx) & set(ref_idx)):
            if cur_idx[name] != ref_idx[name]:
                out.append(f"index-differs: {t}.{name}")

    for s in sorted(set(current["sequences"]) - set(reference["sequences"])):
        out.append(f"sequence-only-in-current: {s}")
    for s in sorted(set(reference["sequences"]) - set(current["sequences"])):
        out.append(f"sequence-missing-in-current: {s}")

    if current["enums"] != reference["enums"]:
        cur_e = {e["name"]: e["labels"] for e in current["enums"]}
        ref_e = {e["name"]: e["labels"] for e in reference["enums"]}
        for name in sorted(set(cur_e) - set(ref_e)):
            out.append(f"enum-only-in-current: {name}")
        for name in sorted(set(ref_e) - set(cur_e)):
            out.append(f"enum-missing-in-current: {name}")
        for name in sorted(set(cur_e) & set(ref_e)):
            if cur_e[name] != ref_e[name]:
                out.append(f"enum-differs: {name} current={cur_e[name]} reference={ref_e[name]}")

    cur_f, ref_f = set(current["functions"]), set(reference["functions"])
    for f in sorted(cur_f - ref_f):
        out.append(f"function-only-in-current: {f}")
    for f in sorted(ref_f - cur_f):
        out.append(f"function-missing-in-current: {f}")

    return out


__all__ = [
    "collect_manifest",
    "diff_manifests",
    "manifest_fingerprint",
]
