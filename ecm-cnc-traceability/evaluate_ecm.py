#!/usr/bin/env python3
"""
ECM extraction evaluation.

Compares model predictions (JSONL from ecm_extraction.py) against a
hand-labeled gold file (same JSONL schema). Produces paper-ready numbers:

  - Per-entity-type precision / recall / F1
  - Macro and micro averages
  - Strict (text+type) and relaxed (type+normalized form) scoring
  - Change-event P/R/F1 (action + target match)
  - Trace-link P/R/F1 (id + kind exact match)
  - Regulation hallucination rate vs. closed vocabulary
  - Coverage stats (gold vs. pred overlap)
  - Per-record error log (FP/FN spans, hallucinations)

Both files must be JSONL where each line is a NoteExtraction object
(as emitted by ecm_extraction.py). The gold file is produced by hand
using the same schema.

Usage:
    python evaluate_ecm.py \\
        --gold gold.jsonl \\
        --pred ecm_extractions.jsonl \\
        --exclude G937,G948 \\
        --report eval_report.md \\
        --errors eval_errors.csv

Always exclude work orders that were used as few-shot exemplars in the
extraction prompt (G937, G948 by default in this project) to avoid
training leakage in the eval set.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# Schema lives in ecm_extraction.py; both files must sit in the same dir.
try:
    from ecm_extraction import NoteExtraction  # noqa: F401  (re-validation if needed)
except ImportError:
    print("WARN: ecm_extraction.py not importable; skipping schema re-validation.",
          file=sys.stderr)

# Closed vocabulary for regulation hallucination check.
# Extend as your domain expands; anything not here is flagged.
VALID_REGULATIONS = {
    "UL", "CSA", "CE", "NRTL", "CCC", "KC", "PSE", "BIS",
    "GB", "JIS", "EN", "ISO", "ANSI", "OSHA", "ROHS", "REACH", "FCC",
}


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #

def load_jsonl(path: Path) -> tuple[dict, int]:
    """Returns (records keyed by work_order, n_error_entries)."""
    records: dict[str, dict] = {}
    n_err = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "_error" in obj:
                n_err += 1
                continue
            wo = obj.get("work_order")
            if wo is None:
                continue
            records[str(wo)] = obj
    return records, n_err


# --------------------------------------------------------------------------- #
# Metric helpers
# --------------------------------------------------------------------------- #

def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


# Canonical entity-type map: case- and separator-insensitive, so a predicted
# "component" / "exception_ticket" scores against gold "Component" /
# "ExceptionTicket" rather than failing on letter case (v2, IJAMT revision).
_CANON_TYPES = {
    "component": "Component", "specification": "Specification",
    "regulation": "Regulation", "exceptionticket": "ExceptionTicket",
    "responsibleparty": "ResponsibleParty",
    # legacy draft-taxonomy aliases (early prompt/schema generations)
    "specvalue": "Specification", "spec": "Specification",
    "part": "Component",
}
GOLD_TYPES = ("Component", "Specification", "Regulation",
              "ExceptionTicket", "ResponsibleParty")


def canon_type(t: str) -> str:
    key = (t or "").replace("_", "").replace("-", "").replace(" ", "").lower()
    return _CANON_TYPES.get(key, (t or "").strip())


def _pnorm(x: str) -> str:
    import unicodedata as _u
    x = _u.normalize("NFKC", x or "")
    return "".join(x.split()).casefold()


def char_jaccard(a: str, b: str) -> float:
    A, B = set(a), set(b)
    if not A and not B:
        return 1.0
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def relaxed_match(a: str, b: str, tau: float = 0.5) -> bool:
    """Paper Eq.(match): normalized equality OR containment OR
    character-Jaccard >= tau."""
    na, nb = _pnorm(a), _pnorm(b)
    if not na or not nb:
        return na == nb
    if na == nb or na in nb or nb in na:
        return True
    return char_jaccard(na, nb) >= tau


def ent_key_strict(e: dict) -> tuple[str, str]:
    return (e.get("text", "").strip(), canon_type(e.get("type", "")))


def ent_key_relaxed(e: dict) -> tuple[str, str]:
    # Type + normalized form (falling back to lowercased text).
    norm = (e.get("normalized") or e.get("text", "")).strip().lower()
    return (canon_type(e.get("type", "")), norm)


# --------------------------------------------------------------------------- #
# Entity eval
# --------------------------------------------------------------------------- #

def eval_entities(gold: dict, pred: dict, mode: str):
    """Per-record greedy matching within canonical entity type.
    mode='strict'  : exact normalized-text equality
    mode='relaxed' : paper Eq.(match) predicate (eq | containment | Jaccard>=.5)
    Returns per-type tp/fp/fn Counters and error rows."""
    tp, fp, fn = Counter(), Counter(), Counter()
    errors = []
    for wo in gold:
        if wo not in pred:
            continue
        g_list = [(canon_type(e.get("type", "")), (e.get("text") or "").strip())
                  for e in gold[wo].get("entities") or []]
        p_list = [(canon_type(e.get("type", "")), (e.get("text") or "").strip())
                  for e in pred[wo].get("entities") or []]
        used = [False] * len(g_list)
        for ptype, ptext in p_list:
            hit = -1
            for i, (gtype, gtext) in enumerate(g_list):
                if used[i] or gtype != ptype:
                    continue
                if mode == "strict":
                    ok = _pnorm(ptext) == _pnorm(gtext)
                else:
                    ok = relaxed_match(ptext, gtext)
                if ok:
                    hit = i
                    break
            if hit >= 0:
                used[hit] = True
                tp[ptype] += 1
            else:
                fp[ptype] += 1
                errors.append({"work_order": wo, "level": f"entity_{mode}",
                               "error": "false_positive", "type": ptype,
                               "pred": ptext, "gold": ""})
        for i, (gtype, gtext) in enumerate(g_list):
            if not used[i]:
                fn[gtype] += 1
                errors.append({"work_order": wo, "level": f"entity_{mode}",
                               "error": "false_negative", "type": gtype,
                               "pred": "", "gold": gtext})
    return tp, fp, fn, errors

# --------------------------------------------------------------------------- #
# Change-event eval (relaxed: action exact, target substring either way)
# --------------------------------------------------------------------------- #

def eval_change_events(gold: dict, pred: dict):
    """Greedy per-record alignment: casefolded action equality AND
    relaxed target match (paper Eq.(match) predicate)."""
    tp = fp = fn = 0
    errors = []
    for wo in gold:
        if wo not in pred:
            continue
        g = [((c.get("action") or "").strip().lower(),
              (c.get("target") or "").strip())
             for c in gold[wo].get("change_events") or []]
        p = [((c.get("action") or "").strip().lower(),
              (c.get("target") or "").strip())
             for c in pred[wo].get("change_events") or []]
        used = [False] * len(g)
        for pa, pt in p:
            hit = -1
            for i, (ga, gt) in enumerate(g):
                if used[i] or ga != pa:
                    continue
                if relaxed_match(pt, gt):
                    hit = i
                    break
            if hit >= 0:
                used[hit] = True
                tp += 1
            else:
                fp += 1
                errors.append({"work_order": wo, "level": "event",
                               "error": "false_positive", "type": pa,
                               "pred": pt, "gold": ""})
        for i, (ga, gt) in enumerate(g):
            if not used[i]:
                fn += 1
                errors.append({"work_order": wo, "level": "event",
                               "error": "false_negative", "type": ga,
                               "pred": "", "gold": gt})
    return tp, fp, fn, errors

# --------------------------------------------------------------------------- #
# Trace-link eval (id + kind exact)
# --------------------------------------------------------------------------- #

def eval_trace_links(gold: dict, pred: dict):
    """Greedy per-record matching: casefolded kind equality AND relaxed id
    match (paper protocol: a bare identifier matches the descriptive
    reference that contains it)."""
    tp = fp = fn = 0
    errors = []
    for wo in gold:
        if wo not in pred:
            continue
        g = [((t.get("kind") or "").strip().lower(), (t.get("id") or "").strip())
             for t in gold[wo].get("trace_links") or []]
        p = [((t.get("kind") or "").strip().lower(), (t.get("id") or "").strip())
             for t in pred[wo].get("trace_links") or []]
        used = [False] * len(g)
        for pk, pid in p:
            hit = -1
            for i, (gk, gid) in enumerate(g):
                if used[i] or gk != pk:
                    continue
                if relaxed_match(pid, gid):
                    hit = i
                    break
            if hit >= 0:
                used[hit] = True
                tp += 1
            else:
                fp += 1
                errors.append({"work_order": wo, "level": "link",
                               "error": "false_positive", "type": pk,
                               "pred": pid, "gold": ""})
        for i, (gk, gid) in enumerate(g):
            if not used[i]:
                fn += 1
                errors.append({"work_order": wo, "level": "link",
                               "error": "false_negative", "type": gk,
                               "pred": "", "gold": gid})
    return tp, fp, fn, errors

# --------------------------------------------------------------------------- #
# Hallucination check on regulations
# --------------------------------------------------------------------------- #

def regulation_hallucinations(
    pred: dict, valid: set[str]
) -> tuple[int, list[dict], float]:
    valid_upper = {v.upper() for v in valid}
    total = 0
    invalid: list[dict] = []
    for wo, rec in pred.items():
        for reg in rec.get("regulations") or []:
            total += 1
            if reg.strip().upper() not in valid_upper:
                invalid.append({"work_order": wo, "regulation": reg})
    rate = len(invalid) / total if total else 0.0
    return total, invalid, rate



# --------------------------------------------------------------------------- #
# v2 additions (IJAMT revision): bootstrap CIs, truncation stratification,
# trace-link relational-error taxonomy.  CLI remains backward compatible.
# --------------------------------------------------------------------------- #

import random
import unicodedata


def _norm(s: str) -> str:
    """NFKC + casefold + strip all whitespace (matches paper's nu(.))."""
    s = unicodedata.normalize("NFKC", s or "")
    return "".join(s.split()).casefold()


def record_is_truncated(rec: dict, trunc_len: int = 255) -> Optional[bool]:
    """True/False if determinable, None if the record carries no note text."""
    if rec.get("is_truncated") is not None:
        return bool(rec["is_truncated"])
    note = rec.get("note")
    if note is None:
        return None
    return len(note) >= trunc_len


def subset(d: dict, wos) -> dict:
    return {w: d[w] for w in wos if w in d}


def micro_from_counters(tp: dict, fp: dict, fn: dict) -> tuple[float, float, float]:
    return prf(sum(tp.values()), sum(fp.values()), sum(fn.values()))


def macro_from_counters(tp: dict, fp: dict, fn: dict) -> tuple[float, float, float]:
    types = set(GOLD_TYPES)
    if not types:
        return 0.0, 0.0, 0.0
    ps = rs = fs = 0.0
    for t in types:
        p, r, f = prf(tp.get(t, 0), fp.get(t, 0), fn.get(t, 0))
        ps += p; rs += r; fs += f
    n = len(types)
    return ps / n, rs / n, fs / n


def metrics_for_wos(gold: dict, pred: dict, wos: list[str]) -> dict:
    """All headline metrics computed over a (multi)set of work orders.
    Duplicates in `wos` are honored (bootstrap resampling)."""
    # Build duplicated views by aliasing keys.
    g2, p2 = {}, {}
    for i, w in enumerate(wos):
        k = f"{w}#{i}"
        if w in gold:
            g2[k] = gold[w]
        if w in pred:
            p2[k] = pred[w]
    tp_s, fp_s, fn_s, _ = eval_entities(g2, p2, "strict")
    tp_r, fp_r, fn_r, _ = eval_entities(g2, p2, "relaxed")
    ev = eval_change_events(g2, p2)
    tl = eval_trace_links(g2, p2)
    out = {}
    out["ent_strict_macro"] = macro_from_counters(tp_s, fp_s, fn_s)
    out["ent_strict_micro"] = micro_from_counters(tp_s, fp_s, fn_s)
    out["ent_relaxed_macro"] = macro_from_counters(tp_r, fp_r, fn_r)
    out["ent_relaxed_micro"] = micro_from_counters(tp_r, fp_r, fn_r)
    out["event"] = prf(*ev[:3])
    out["link"] = prf(*tl[:3])
    return out


METRIC_KEYS = ["ent_strict_macro", "ent_strict_micro", "ent_relaxed_macro",
               "ent_relaxed_micro", "event", "link"]
PRF_NAMES = ["P", "R", "F1"]


def bootstrap_cis(gold: dict, pred: dict, wos: list[str],
                  n_boot: int, seed: int) -> dict:
    """Nonparametric bootstrap over records. Returns
    {metric: {P/R/F1: (lo, hi)}} with 95% percentile intervals."""
    rng = random.Random(seed)
    samples: dict[str, list[list[float]]] = {k: [[], [], []] for k in METRIC_KEYS}
    n = len(wos)
    for _ in range(n_boot):
        draw = [wos[rng.randrange(n)] for _ in range(n)]
        m = metrics_for_wos(gold, pred, draw)
        for k in METRIC_KEYS:
            for j in range(3):
                samples[k][j].append(m[k][j])
    def pct(v, q):
        v = sorted(v)
        idx = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
        return v[idx]
    cis = {}
    for k in METRIC_KEYS:
        cis[k] = {}
        for j, name in enumerate(PRF_NAMES):
            vals = samples[k][j]
            cis[k][name] = (pct(vals, 0.025), pct(vals, 0.975))
    return cis


def link_error_taxonomy(gold: dict, pred: dict, wos: list[str]) -> tuple[dict, list[dict]]:
    """Classify trace-link FPs (under the relaxed matching protocol):
       relational / non_attested / kind_only. Counts TPs and FNs too."""
    counts = Counter()
    rows: list[dict] = []
    for wo in wos:
        if wo not in gold or wo not in pred:
            continue
        note = gold[wo].get("note") or pred[wo].get("note") or ""
        nnote = _norm(note)
        g = [((t.get("kind") or "").strip().lower(), (t.get("id") or "").strip())
             for t in gold[wo].get("trace_links") or []]
        p = [((t.get("kind") or "").strip().lower(), (t.get("id") or "").strip())
             for t in pred[wo].get("trace_links") or []]
        used = [False] * len(g)
        fps = []
        for pk, pid in p:
            hit = -1
            for i, (gk, gid) in enumerate(g):
                if used[i] or gk != pk:
                    continue
                if relaxed_match(pid, gid):
                    hit = i
                    break
            if hit >= 0:
                used[hit] = True
                counts["tp"] += 1
            else:
                fps.append((pk, pid))
        gold_ids = [gid for _, gid in g]
        for pk, pid in fps:
            attested = bool(nnote) and _norm(pid) in nnote
            id_matches_gold = any(relaxed_match(pid, gid) for gid in gold_ids)
            if id_matches_gold:
                cls = "kind_only"
            elif attested:
                cls = "relational"
            else:
                cls = "non_attested"
            counts[cls] += 1
            rows.append({"work_order": wo, "class": cls, "id": pid,
                         "kind": pk, "attested_in_note": attested,
                         "note_excerpt": note[:120]})
        counts["fn"] += used.count(False)
    return dict(counts), rows


def stratified_block(gold: dict, pred: dict, wos: list[str],
                     trunc_len: int) -> tuple[dict, dict, list[str], list[str], int]:
    """Split eval set by truncation status; returns metrics for both strata."""
    trunc, full, unknown = [], [], 0
    for wo in wos:
        st = record_is_truncated(gold.get(wo, {}), trunc_len)
        if st is None:
            st = record_is_truncated(pred.get(wo, {}), trunc_len)
        if st is None:
            unknown += 1
        elif st:
            trunc.append(wo)
        else:
            full.append(wo)
    m_t = metrics_for_wos(gold, pred, trunc) if trunc else None
    m_f = metrics_for_wos(gold, pred, full) if full else None
    return m_t, m_f, trunc, full, unknown


def fmt_ci(point: tuple, ci: dict) -> str:
    return (f"P={point[0]:.3f} [{ci['P'][0]:.3f},{ci['P'][1]:.3f}]  "
            f"R={point[1]:.3f} [{ci['R'][0]:.3f},{ci['R'][1]:.3f}]  "
            f"F1={point[2]:.3f} [{ci['F1'][0]:.3f},{ci['F1'][1]:.3f}]")


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def fmt_prf_table(name: str, results: dict[str, tuple[int, int, int]]) -> str:
    """results: {type_name: (tp, fp, fn)} -> markdown table with macro+micro."""
    lines = [f"### {name}", "",
             "| Type | TP | FP | FN | P | R | F1 |",
             "|------|----|----|----|---|---|----|"]
    all_types = sorted(results)
    sum_tp = sum_fp = sum_fn = 0
    macro_p = macro_r = macro_f = 0.0
    for t in all_types:
        tp, fp, fn = results[t]
        p, r, f = prf(tp, fp, fn)
        sum_tp += tp; sum_fp += fp; sum_fn += fn
        macro_p += p; macro_r += r; macro_f += f
        lines.append(f"| {t} | {tp} | {fp} | {fn} | "
                     f"{p:.3f} | {r:.3f} | {f:.3f} |")
    n = max(len(all_types), 1)
    mip, mir, mif = prf(sum_tp, sum_fp, sum_fn)
    lines.append(f"| **micro** | {sum_tp} | {sum_fp} | {sum_fn} | "
                 f"{mip:.3f} | {mir:.3f} | {mif:.3f} |")
    lines.append(f"| **macro** | - | - | - | "
                 f"{macro_p/n:.3f} | {macro_r/n:.3f} | {macro_f/n:.3f} |")
    return "\n".join(lines) + "\n"


def write_report(
    report_path: Path,
    coverage: dict,
    ent_strict: dict, ent_relaxed: dict,
    event_metrics: tuple, trace_metrics: tuple,
    halluc: tuple,
    pred_errors_in_jsonl: int, gold_errors_in_jsonl: int,
) -> None:
    out = ["# ECM Extraction Evaluation Report", ""]
    out.append("## Coverage")
    out.append("")
    out.append(f"- Gold records loaded: **{coverage['n_gold']}**")
    out.append(f"- Pred records loaded: **{coverage['n_pred']}**")
    out.append(f"- Excluded work orders: {coverage['excluded']}")
    out.append(f"- Overlap (eval set size): **{coverage['n_overlap']}**")
    out.append(f"- Gold-only (model missed entirely): {coverage['gold_only']}")
    out.append(f"- Pred-only (no gold to score against): {coverage['pred_only']}")
    out.append(f"- Pred-side schema/validation failures in JSONL: {pred_errors_in_jsonl}")
    out.append(f"- Gold-side error lines in JSONL: {gold_errors_in_jsonl}")
    out.append("")

    out.append("## Entity extraction — STRICT (text + type exact)")
    out.append("")
    out.append(fmt_prf_table("Per-entity-type", ent_strict))

    out.append("## Entity extraction — RELAXED (type + normalized form)")
    out.append("")
    out.append(fmt_prf_table("Per-entity-type", ent_relaxed))

    tp, fp, fn = event_metrics
    p, r, f = prf(tp, fp, fn)
    out.append("## Change events (action exact, target substring match)")
    out.append("")
    out.append(f"- TP={tp}  FP={fp}  FN={fn}")
    out.append(f"- **P={p:.3f}  R={r:.3f}  F1={f:.3f}**")
    out.append("")

    tp, fp, fn = trace_metrics
    p, r, f = prf(tp, fp, fn)
    out.append("## Trace links (id + kind exact)")
    out.append("")
    out.append(f"- TP={tp}  FP={fp}  FN={fn}")
    out.append(f"- **P={p:.3f}  R={r:.3f}  F1={f:.3f}**")
    out.append("")

    total, invalid, rate = halluc
    out.append("## Regulation hallucination check")
    out.append("")
    out.append(f"- Closed vocabulary size: {len(VALID_REGULATIONS)}")
    out.append(f"- Total regulations extracted: {total}")
    out.append(f"- Invalid (not in vocab): {len(invalid)}")
    out.append(f"- **Hallucination rate: {rate:.3f}**")
    if invalid:
        out.append("")
        out.append("Examples of invalid regulation strings:")
        for ex in invalid[:10]:
            out.append(f"  - {ex['work_order']}: `{ex['regulation']}`")
    out.append("")

    report_path.write_text("\n".join(out), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True, type=Path)
    ap.add_argument("--pred", required=True, type=Path)
    ap.add_argument("--exclude", default="G937,G948",
                    help="Comma-separated work orders to exclude (few-shot exemplars).")
    ap.add_argument("--report", default="eval_report.md", type=Path)
    ap.add_argument("--errors", default="eval_errors.csv", type=Path)
    ap.add_argument("--bootstrap", type=int, default=0,
                    help="N bootstrap resamples for 95%% CIs (0 = off; paper uses 2000).")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stratify-truncation", action="store_true",
                    help="Also report all metrics split by 255-char truncation status.")
    ap.add_argument("--trunc-len", type=int, default=255)
    ap.add_argument("--link-errors", default="link_errors.csv", type=Path,
                    help="CSV dump of trace-link FP taxonomy (relational vs non-attested).")
    args = ap.parse_args()

    gold, gold_err = load_jsonl(args.gold)
    pred, pred_err = load_jsonl(args.pred)

    excluded = {w.strip() for w in args.exclude.split(",") if w.strip()}
    for wo in list(gold):
        if wo in excluded:
            gold.pop(wo)
    for wo in list(pred):
        if wo in excluded:
            pred.pop(wo)

    overlap = set(gold) & set(pred)
    coverage = {
        "n_gold": len(gold),
        "n_pred": len(pred),
        "n_overlap": len(overlap),
        "gold_only": len(set(gold) - set(pred)),
        "pred_only": len(set(pred) - set(gold)),
        "excluded": sorted(excluded),
    }

    if not overlap:
        sys.exit("No overlapping work orders between gold and pred. "
                 "Check that work_order strings match exactly.")

    tp_s, fp_s, fn_s, errs_s = eval_entities(gold, pred, "strict")
    tp_r, fp_r, fn_r, errs_r = eval_entities(gold, pred, "relaxed")
    types = set(tp_s) | set(fp_s) | set(fn_s) | set(tp_r) | set(fp_r) | set(fn_r)
    ent_strict = {t: (tp_s.get(t, 0), fp_s.get(t, 0), fn_s.get(t, 0)) for t in types}
    ent_relaxed = {t: (tp_r.get(t, 0), fp_r.get(t, 0), fn_r.get(t, 0)) for t in types}

    event_metrics = eval_change_events(gold, pred)
    trace_metrics = eval_trace_links(gold, pred)
    halluc = regulation_hallucinations(pred, VALID_REGULATIONS)

    write_report(args.report, coverage, ent_strict, ent_relaxed,
                 event_metrics[:3], trace_metrics[:3], halluc,
                 pred_errors_in_jsonl=pred_err,
                 gold_errors_in_jsonl=gold_err)

    # Per-record errors CSV
    import csv
    all_errs = errs_s + errs_r + event_metrics[3] + trace_metrics[3]
    for h in halluc[1]:
        all_errs.append({"work_order": h["work_order"],
                         "kind": "hallucinated_regulation",
                         "type": "regulation",
                         "value": h["regulation"]})
    with args.errors.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh,
            fieldnames=["work_order", "kind", "type", "value",
                        "level", "error", "pred", "gold"],
            extrasaction="ignore")
        w.writeheader()
        w.writerows(all_errs)

    # Stdout summary
    print(f"Eval set size (after exclude): {len(overlap)} work orders")
    print(f"Excluded: {sorted(excluded)}")
    mip, mir, mif = prf(
        sum(v[0] for v in ent_strict.values()),
        sum(v[1] for v in ent_strict.values()),
        sum(v[2] for v in ent_strict.values()),
    )
    print(f"Entity (strict) micro F1: {mif:.3f}  P={mip:.3f}  R={mir:.3f}")
    mip, mir, mif = prf(
        sum(v[0] for v in ent_relaxed.values()),
        sum(v[1] for v in ent_relaxed.values()),
        sum(v[2] for v in ent_relaxed.values()),
    )
    print(f"Entity (relaxed) micro F1: {mif:.3f}  P={mip:.3f}  R={mir:.3f}")
    p, r, f = prf(*event_metrics[:3])
    print(f"Change events F1: {f:.3f}  P={p:.3f}  R={r:.3f}")
    p, r, f = prf(*trace_metrics[:3])
    print(f"Trace links F1: {f:.3f}  P={p:.3f}  R={r:.3f}")
    print(f"Regulation hallucination rate: {halluc[2]:.3f}  "
          f"({len(halluc[1])}/{halluc[0]})")
    wos = sorted(overlap)

    # ---- v2: trace-link FP taxonomy (R3 comment 4) ----
    tax_counts, tax_rows = link_error_taxonomy(gold, pred, wos)
    with args.link_errors.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["work_order", "class", "id", "kind",
                                           "attested_in_note", "note_excerpt"])
        w.writeheader(); w.writerows(tax_rows)
    fp_rel = tax_counts.get("relational", 0)
    fp_non = tax_counts.get("non_attested", 0)
    fp_kind = tax_counts.get("kind_only", 0)
    fp_all = fp_rel + fp_non + fp_kind
    print(f"\nTrace-link FP taxonomy (n={fp_all}): "
          f"relational={fp_rel}  non-attested={fp_non}  kind-only={fp_kind}")
    if fp_all:
        print(f"  -> share of FPs surviving attestation (relational+kind): "
              f"{(fp_rel+fp_kind)/fp_all:.1%}")
    print(f"  -> per-case dump: {args.link_errors}")

    # ---- v2: truncation-stratified metrics (R3 comment 3) ----
    if args.stratify_truncation:
        m_t, m_f, wos_t, wos_f, unk = stratified_block(gold, pred, wos, args.trunc_len)
        print(f"\nTruncation-stratified metrics "
              f"(truncated n={len(wos_t)}, non-truncated n={len(wos_f)}, unknown {unk}):")
        for label, m in (("TRUNCATED", m_t), ("NON-TRUNCATED", m_f)):
            if m is None:
                print(f"  {label}: (empty stratum)"); continue
            print(f"  {label}:")
            print(f"    entity strict  macro P/R/F1 = "
                  f"{m['ent_strict_macro'][0]:.3f}/{m['ent_strict_macro'][1]:.3f}/{m['ent_strict_macro'][2]:.3f}")
            print(f"    entity relaxed macro P/R/F1 = "
                  f"{m['ent_relaxed_macro'][0]:.3f}/{m['ent_relaxed_macro'][1]:.3f}/{m['ent_relaxed_macro'][2]:.3f}")
            print(f"    events  P/R/F1 = {m['event'][0]:.3f}/{m['event'][1]:.3f}/{m['event'][2]:.3f}")
            print(f"    links   P/R/F1 = {m['link'][0]:.3f}/{m['link'][1]:.3f}/{m['link'][2]:.3f}")

    # ---- v2: bootstrap 95% CIs (R1 1.2 / R3 comment 1) ----
    if args.bootstrap > 0:
        point = metrics_for_wos(gold, pred, wos)
        cis = bootstrap_cis(gold, pred, wos, args.bootstrap, args.seed)
        print(f"\nBootstrap 95% CIs ({args.bootstrap} resamples over "
              f"{len(wos)} records, seed {args.seed}):")
        label_map = {
            "ent_strict_macro":  "entity strict  macro",
            "ent_strict_micro":  "entity strict  micro",
            "ent_relaxed_macro": "entity relaxed macro",
            "ent_relaxed_micro": "entity relaxed micro",
            "event":             "change events       ",
            "link":              "trace links         ",
        }
        for k in METRIC_KEYS:
            print(f"  {label_map[k]}: {fmt_ci(point[k], cis[k])}")

    print(f"\nReport -> {args.report}")
    print(f"Errors -> {args.errors}")


if __name__ == "__main__":
    main()
