#!/usr/bin/env python3
"""
Comparison baselines for the ECM extraction study (IJAMT revision, R3 comment 2).

Three non-finetuned baselines, all emitting JSONL compatible with
evaluate_ecm.py (NoteExtraction-shaped rows):

  --mode rules      Deterministic regex + closed-vocabulary extractor.
                    No model, no GPU; the floor any learned system must beat.
  --mode zeroshot   Schema-in-prompt zero-shot extraction with any
                    OpenAI-compatible model (Ollama local by default).
  --mode fewshot    Same, plus k in-context exemplars drawn FROM THE GOLD FILE
                    (default G937,G948 — the two exemplars already excluded
                    from evaluation), restoring an honest "few-shot" row.

Input records come from the gold file itself (--gold), so every baseline is
scored on exactly the same held-out notes as the fine-tuned model:

    python ecm_baselines.py --mode rules    --gold gold.jsonl --tag rules
    python ecm_baselines.py --mode zeroshot --gold gold.jsonl \\
        --base-url http://localhost:11434/v1 --model qwen2.5:7b-instruct \\
        --tag qwen7b-zeroshot
    python ecm_baselines.py --mode fewshot  --gold gold.jsonl \\
        --base-url http://localhost:11434/v1 --model qwen2.5:7b-instruct \\
        --exemplars G937,G948 --tag qwen7b-fewshot

    python evaluate_ecm.py --gold gold.jsonl \\
        --pred ecm_extractions_rules.jsonl --exclude G937,G948 \\
        --bootstrap 2000 --stratify-truncation

Determinism: temperature 0; rules mode is fully deterministic.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------- #
# Shared: closed vocabularies and the JSON contract
# --------------------------------------------------------------------------- #

VALID_REGULATIONS = [
    "UL", "CSA", "CE", "NRTL", "CCC", "KC", "PSE", "BIS",
    "GB", "JIS", "EN", "ISO", "ANSI", "OSHA", "ROHS", "REACH", "FCC",
]

SCHEMA_DOC = """Return ONLY a JSON object with exactly these fields:
{
  "work_order": string or null,
  "entities": [ {"text": verbatim span, "type": one of
      "Component" | "Specification" | "Regulation" |
      "ExceptionTicket" | "ResponsibleParty"} ],
  "change_events": [ {"action": one of "add"|"remove"|"modify"|"require",
      "target": string, "detail": string or null,
      "triggered_by": string or null} ],
  "trace_links": [ {"id": string, "kind": one of
      "exception_ticket"|"sales_order"|"original_work_order"|"other"} ],
  "regulations": [ string ]
}
Extract only content present in the note. Entity text must be verbatim
from the note. If nothing of a category is present, return an empty list."""

SYSTEM_PROMPT = (
    "You are an information-extraction system for CNC lathe engineering-change "
    "notes written in mixed Traditional Chinese and English. Notes may be "
    "truncated at 255 characters mid-sentence. " + SCHEMA_DOC
)


def load_gold(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "_error" in obj or obj.get("work_order") is None:
                continue
            rows.append(obj)
    return rows


def out_path(tag: str) -> Path:
    return Path(f"ecm_extractions_{tag}.jsonl")


# --------------------------------------------------------------------------- #
# Mode 1: rule-based extractor
# --------------------------------------------------------------------------- #

# Trace-link identifier grammars observed in the corpus.
RE_QI = re.compile(r"\bQI[-–]?\d{3,6}\b", re.I)
RE_SALES = re.compile(r"\bB[-–]?\d{6}\b", re.I)
RE_WO = re.compile(r"\bG\d{3,4}[A-Z]?\b")
# Specification-like value strings (number + unit, model codes, colors).
RE_SPEC = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:mm|MM|cm|rpm|RPM|kw|KW|kW|HP|hp|V|A|T|m/min)\b"
    r"|RAL\s?\d{4}"
    r"|\bLA\s?\d{2,3}\b")
# Minimal component gazetteer (extend via --gazetteer file, one term per line).
DEFAULT_GAZETTEER = [
    "尾座", "刀塔", "主軸", "排屑機", "鐵屑車", "床台", "滑板", "床鞍",
    "油壓箱", "冷卻幫浦", "潤滑幫浦", "齒箱", "床護", "護罩", "馬達",
    "心軸", "夾頭", "T型槽", "凹口塊", "銘牌", "電箱",
]
# Change-action trigger patterns -> (action, how to get target)
ACTION_PATTERNS = [
    (re.compile(r"(加裝|增加|加配|追加)\s*([^\s，。,;；]{1,12})"), "add"),
    (re.compile(r"(取消|移除|刪除|不含)\s*([^\s，。,;；]{1,12})"), "remove"),
    (re.compile(r"([^\s，。,;；]{1,12})\s*(?:改為|改成|改|更改為|變更為|→|->)\s*([^\s，。,;；]{1,12})"), "modify"),
    (re.compile(r"(需|須|需求|要求)\s*([^\s，。,;；]{1,12})"), "require"),
]


def rules_extract(wo: str, note: str, gazetteer: list[str]) -> dict:
    entities, links, regs, events = [], [], [], []
    seen = set()

    def add_ent(text: str, etype: str):
        k = (text, etype)
        if text and k not in seen:
            seen.add(k)
            entities.append({"text": text, "type": etype})

    for m in RE_QI.finditer(note):
        add_ent(m.group(0), "ExceptionTicket")
        links.append({"id": m.group(0), "kind": "exception_ticket"})
    for m in RE_SALES.finditer(note):
        links.append({"id": m.group(0), "kind": "sales_order"})
    for m in RE_WO.finditer(note):
        if m.group(0) != wo:  # a reference to a *different* order
            links.append({"id": m.group(0), "kind": "original_work_order"})
    for m in RE_SPEC.finditer(note):
        add_ent(m.group(0), "Specification")
    up = note.upper()
    for reg in VALID_REGULATIONS:
        if re.search(rf"(?<![A-Z]){reg}(?![A-Z])", up):
            regs.append(reg)
            add_ent(reg, "Regulation")
    for term in gazetteer:
        if term in note:
            add_ent(term, "Component")
    for pat, action in ACTION_PATTERNS:
        for m in pat.finditer(note):
            target = m.group(2) if action != "modify" else m.group(1)
            detail = None if action != "modify" else f"{m.group(1)} -> {m.group(2)}"
            events.append({"action": action, "target": target,
                           "detail": detail, "triggered_by": None})

    # de-duplicate links
    uniq, lseen = [], set()
    for l in links:
        k = (l["id"].upper(), l["kind"])
        if k not in lseen:
            lseen.add(k)
            uniq.append(l)
    return {"work_order": wo, "note": note, "entities": entities,
            "change_events": events, "trace_links": uniq,
            "regulations": sorted(set(regs))}


# --------------------------------------------------------------------------- #
# Modes 2-3: prompted extraction via OpenAI-compatible endpoint
# --------------------------------------------------------------------------- #

def build_messages(note: str, wo: str, exemplars: list[dict]) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex in exemplars:
        ex_note = ex.get("note") or ""
        target = {k: ex.get(k) for k in
                  ("work_order", "entities", "change_events",
                   "trace_links", "regulations")}
        msgs.append({"role": "user",
                     "content": f"Work order: {ex['work_order']}\nNote: {ex_note}"})
        msgs.append({"role": "assistant",
                     "content": json.dumps(target, ensure_ascii=False)})
    msgs.append({"role": "user", "content": f"Work order: {wo}\nNote: {note}"})
    return msgs


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in response")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON in response")


def prompted_extract(rows: list[dict], exemplars: list[dict], args) -> list[dict]:
    from openai import OpenAI
    client = OpenAI(base_url=args.base_url, api_key=args.api_key or "ollama")
    out = []
    for i, r in enumerate(rows, 1):
        wo, note = r["work_order"], r.get("note") or ""
        msgs = build_messages(note, wo, exemplars)
        try:
            resp = client.chat.completions.create(
                model=args.model, messages=msgs,
                temperature=0.0, max_tokens=args.max_tokens)
            obj = extract_json(resp.choices[0].message.content or "")
            obj["work_order"] = wo
            obj["note"] = note
            for key in ("entities", "change_events", "trace_links", "regulations"):
                obj.setdefault(key, [])
            out.append(obj)
        except Exception as e:  # keep going; mark the failure
            out.append({"work_order": wo, "note": note, "_error": str(e)})
        if i % 5 == 0 or i == len(rows):
            print(f"  ...{i}/{len(rows)}", file=sys.stderr)
        time.sleep(args.sleep)
    return out


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rules", "zeroshot", "fewshot"],
                    required=True)
    ap.add_argument("--gold", required=True, type=Path,
                    help="Gold JSONL; supplies the notes to extract from "
                         "(and the exemplars for --mode fewshot).")
    ap.add_argument("--tag", required=True,
                    help="Output suffix: ecm_extractions_<tag>.jsonl")
    ap.add_argument("--exemplars", default="G937,G948",
                    help="Work orders used as in-context exemplars (fewshot).")
    ap.add_argument("--gazetteer", type=Path, default=None,
                    help="Optional file of component terms, one per line.")
    # provider options (zeroshot / fewshot)
    ap.add_argument("--base-url", default="http://localhost:11434/v1")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--model", default="qwen2.5:7b-instruct")
    ap.add_argument("--max-tokens", type=int, default=1200)
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()

    rows = load_gold(args.gold)
    ex_ids = {w.strip() for w in args.exemplars.split(",") if w.strip()}
    exemplars = [r for r in rows if r["work_order"] in ex_ids]
    targets = [r for r in rows if r["work_order"] not in ex_ids]
    print(f"{len(rows)} gold rows -> {len(targets)} extraction targets "
          f"({len(exemplars)} reserved as exemplars: {sorted(ex_ids)})",
          file=sys.stderr)

    if args.mode == "rules":
        gaz = DEFAULT_GAZETTEER
        if args.gazetteer and args.gazetteer.exists():
            gaz = [l.strip() for l in
                   args.gazetteer.read_text(encoding="utf-8").splitlines()
                   if l.strip()]
        preds = [rules_extract(r["work_order"], r.get("note") or "", gaz)
                 for r in targets]
    elif args.mode == "zeroshot":
        preds = prompted_extract(targets, [], args)
    else:  # fewshot
        if not exemplars:
            sys.exit("fewshot mode needs --exemplars present in the gold file")
        preds = prompted_extract(targets, exemplars, args)

    dest = out_path(args.tag)
    with dest.open("w", encoding="utf-8") as fh:
        for p in preds:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    n_err = sum(1 for p in preds if "_error" in p)
    print(f"wrote {len(preds)} rows ({n_err} errors) -> {dest}")
    print(f"next:  python evaluate_ecm.py --gold {args.gold} --pred {dest} "
          f"--exclude {args.exemplars} --bootstrap 2000 --stratify-truncation")


if __name__ == "__main__":
    main()
