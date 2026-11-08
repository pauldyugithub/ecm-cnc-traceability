#!/usr/bin/env python3
"""
Deterministic post-hoc attestation filter (the paper's second ablation arm).

Reads canonical-format extraction JSONL, drops every value that cannot be
attested in the source note, and writes the filtered JSONL:

  * entities     : kept iff norm(text) is a substring of norm(note)
  * trace_links  : kept iff norm(id)   is a substring of norm(note)
  * regulations  : kept iff in the closed vocabulary AND attested in the note
  * change_events: kept as-is (events are scored on action+target alignment;
                   filtering them is a separate design decision the paper
                   does not make)

Usage:
    python apply_attestation.py --in pred_ft_eval.jsonl \
        --out pred_ft_filtered.jsonl
    python evaluate_ecm_ijamt.py --gold gold_eval.jsonl \
        --pred pred_ft_filtered.jsonl --exclude G937,G948 \
        --bootstrap 2000 --stratify-truncation \
        --link-errors link_errors_ft_filtered.csv
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

VALID_REGULATIONS = {
    "UL", "CSA", "CE", "NRTL", "CCC", "KC", "PSE", "BIS",
    "GB", "JIS", "EN", "ISO", "ANSI", "OSHA", "ROHS", "REACH", "FCC",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return "".join(s.split()).casefold()


def attested(value: str, note_n: str) -> bool:
    v = norm(value)
    return bool(v) and v in note_n


def filter_row(row: dict) -> tuple[dict, dict]:
    note_n = norm(row.get("note") or "")
    stats = {"entities_dropped": 0, "links_dropped": 0, "regs_dropped": 0}
    out = dict(row)

    ents = []
    for e in row.get("entities") or []:
        if attested(e.get("text", ""), note_n):
            ents.append(e)
        else:
            stats["entities_dropped"] += 1
    out["entities"] = ents

    links = []
    for t in row.get("trace_links") or []:
        if attested(t.get("id", ""), note_n):
            links.append(t)
        else:
            stats["links_dropped"] += 1
    out["trace_links"] = links

    regs = []
    for r in row.get("regulations") or []:
        if r.upper() in VALID_REGULATIONS and attested(r, note_n):
            regs.append(r)
        else:
            stats["regs_dropped"] += 1
    out["regulations"] = regs
    return out, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    total = {"entities_dropped": 0, "links_dropped": 0, "regs_dropped": 0}
    n = 0
    with args.inp.open(encoding="utf-8") as fi, \
         args.out.open("w", encoding="utf-8") as fo:
        for line in fi:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "_error" in row:
                fo.write(line + "\n")
                continue
            if not row.get("note"):
                # cannot attest without the source note; pass through untouched
                fo.write(json.dumps(row, ensure_ascii=False) + "\n")
                continue
            out, st = filter_row(row)
            for k in total:
                total[k] += st[k]
            fo.write(json.dumps(out, ensure_ascii=False) + "\n")
            n += 1
    print(f"filtered {n} rows -> {args.out}")
    print(f"dropped: entities {total['entities_dropped']}, "
          f"links {total['links_dropped']}, regulations {total['regs_dropped']}")


if __name__ == "__main__":
    main()
