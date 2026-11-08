#!/usr/bin/env python3
"""
Normalize ECM gold/prediction files into the canonical JSONL that
evaluate_ecm.py scores.

Accepts BOTH naming generations seen in this project, per row:

  A) Worksheet rows  : {wo_id, annotation, gold:{entities, change_events,
                        traceability_links}, is_truncated_255, verified, ...}
  B) Flat rows       : {work_order, note?, entities, change_events,
                        trace_links | traceability_links, regulations?}

and both item-field generations:

  entities : {entity_type|type, value|text, ...}
  events   : {event_type|action, entities|target, from_value, to_value, reason}
  links    : {target_id|id, link_type|kind}

Canonical output per row:
  {work_order, note, is_truncated, entities:[{text,type}],
   change_events:[{action,target,detail,triggered_by}],
   trace_links:[{id,kind}], regulations:[...]}

Event/link type vocabularies are mapped to the canonical enums:
  SpecificationRevision -> modify     ComponentSubstitution -> modify
  QuantityAdjustment    -> modify     StatusTransition      -> modify
  Addition|Add          -> add        Removal|Remove        -> remove
  Requirement|Require   -> require
  CrossOrderReference   -> original_work_order
  ExternalTicket|ExceptionTicketLink -> exception_ticket
  SalesOrderReference   -> sales_order
(unknown values pass through lowercased so nothing is silently dropped)

Usage:
    python gold_to_eval.py --in gold_worksheet_verified.jsonl \\
        --out gold_eval.jsonl [--append-exemplars] [--only-verified]

--append-exemplars adds the two prompt exemplars (G937, G948) from
ecm_extraction.py so that `ecm_baselines.py --mode fewshot` can draw them
from the same file; evaluation still excludes them via --exclude G937,G948.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVENT_MAP = {
    "specificationrevision": "modify",
    "componentsubstitution": "modify",
    "substitution": "modify",
    "quantityadjustment": "modify",
    "statustransition": "modify",
    "specification": "modify", "specify": "modify", "replace": "modify",
    "status": "modify", "componentstatus": "modify", "quantity": "modify",
    "revision": "modify",
    "addition": "add", "add": "add",
    "removal": "remove", "remove": "remove",
    "requirement": "require", "require": "require",
    "modify": "modify",
}
LINK_MAP = {
    "crossorderreference": "original_work_order",
    "originalworkorder": "original_work_order",
    "original_work_order": "original_work_order",
    "workorder": "original_work_order",
    "workorderrevision": "original_work_order",
    "revision": "original_work_order",
    "productionplan": "original_work_order",
    "reference": "original_work_order",
    "externalticket": "exception_ticket",
    "exceptionticketlink": "exception_ticket",
    "exception_ticket": "exception_ticket",
    "salesorderreference": "sales_order",
    "sales_order": "sales_order",
    "other": "other",
}


def map_vocab(value: str, table: dict) -> str:
    key = (value or "").replace("_", "").replace("-", "").strip().lower()
    return table.get(key, (value or "").strip().lower() or "other")


def norm_entity(e) -> dict:
    if isinstance(e, str):
        return {"text": e.strip(), "type": ""}
    return {"text": (e.get("text") or e.get("value") or "").strip(),
            "type": e.get("type") or e.get("entity_type") or ""}


def norm_event(c) -> dict:
    if isinstance(c, str):
        return {"action": "", "target": c.strip(),
                "detail": None, "triggered_by": None}
    raw = c.get("action") or c.get("event_type") or ""
    action = map_vocab(raw, EVENT_MAP)
    target = c.get("target")
    if not target:
        ents = c.get("entities") or []
        target = ents[0] if ents else (c.get("to_value") or "")
    detail = c.get("detail")
    if detail is None and (c.get("from_value") or c.get("to_value")):
        fv, tv = c.get("from_value") or "", c.get("to_value") or ""
        detail = f"{fv} -> {tv}".strip(" ->") or None
    return {"action": action, "target": (target or "").strip(),
            "detail": detail, "triggered_by": c.get("triggered_by") or c.get("reason")}


def norm_link(t) -> dict:
    if isinstance(t, str):
        return {"id": t.strip(), "kind": "other"}
    return {"id": (t.get("id") or t.get("target_id") or "").strip(),
            "kind": map_vocab(t.get("kind") or t.get("link_type") or "", LINK_MAP)}


def normalize_row(row: dict) -> dict | None:
    inner = row.get("gold") if isinstance(row.get("gold"), dict) else row
    wo = row.get("work_order") or row.get("wo_id") or inner.get("work_order")
    if not wo:
        return None
    note = row.get("note") or row.get("annotation") or inner.get("note") or ""
    trunc = row.get("is_truncated")
    if trunc is None:
        trunc = row.get("is_truncated_255")
    if trunc is None and note:
        trunc = len(note) >= 255
    ents = [norm_entity(e) for e in inner.get("entities") or []]
    ents = [e for e in ents if e["text"]]
    events = [norm_event(c) for c in inner.get("change_events") or []]
    links = [norm_link(t) for t in
             (inner.get("trace_links") or inner.get("traceability_links") or [])]
    links = [l for l in links if l["id"]]
    regs = inner.get("regulations")
    if regs is None:
        regs = [e["text"] for e in ents if e["type"] == "Regulation"]
    return {"work_order": str(wo), "note": note, "is_truncated": bool(trunc),
            "entities": ents, "change_events": events,
            "trace_links": links, "regulations": regs}


def exemplar_rows() -> list[dict]:
    """Pull the two few-shot exemplars out of ecm_extraction.py (FEW_SHOTS)."""
    sys.path.insert(0, str(Path(__file__).parent))
    from ecm_extraction import FEWSHOT  # type: ignore
    out = []
    for ex in FEWSHOT:
        row = dict(ex["json"])
        row["note"] = ex["note"]
        out.append(normalize_row(row))
    return [r for r in out if r]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--only-verified", action="store_true",
                    help="Keep only rows with verified=true (worksheet format).")
    ap.add_argument("--append-exemplars", action="store_true",
                    help="Append G937/G948 prompt exemplars from ecm_extraction.py.")
    args = ap.parse_args()

    rows, skipped, unverified = [], 0, 0
    with args.inp.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            if args.only_verified and "verified" in raw and not raw["verified"]:
                unverified += 1
                continue
            r = normalize_row(raw)
            if r is None:
                skipped += 1
                continue
            rows.append(r)

    if args.append_exemplars:
        try:
            rows.extend(exemplar_rows())
        except Exception as e:
            print(f"WARN: could not append exemplars ({e})", file=sys.stderr)

    with args.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_tr = sum(1 for r in rows if r["is_truncated"])
    print(f"wrote {len(rows)} rows -> {args.out} "
          f"(truncated {n_tr}, skipped {skipped}, unverified dropped {unverified})")


if __name__ == "__main__":
    main()
