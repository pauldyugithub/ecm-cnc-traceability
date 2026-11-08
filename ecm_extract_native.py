#!/usr/bin/env python3
"""
Properly-elicited ECM extraction: call cnc-ecm through Ollama's /api/generate
so the model runs under its OWN baked-in training system prompt and template
(including the trailing '{"' prefill), with the raw annotation as the prompt.
This evaluates "the system as trained", not the model under a foreign prompt.

Output rows are native-schema objects wrapped with work_order + note:
  {work_order, note, entities:[{entity_type,value,...}],
   change_events:[{event_type,...}], traceability_links:[{link_type,target_id,...}]}
gold_to_eval.py already normalizes this shape.

Usage:
    python ecm_extract_native.py --csv merged_work_order_specs.csv \
        --model cnc-ecm:latest --out-jsonl ecm_extractions_native.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path


def ollama_generate(host: str, model: str, prompt: str,
                    timeout: int = 300) -> str:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/api/generate", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8")).get("response", "")


def parse_native(completion: str) -> dict:
    """The Modelfile template prefills '{\"' before generation, so the
    returned completion usually lacks the opening brace. Reassemble, then
    parse the first balanced object."""
    text = completion.strip()
    if text.startswith("```"):
        import re
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    if not text.startswith("{"):
        text = '{"' + text.lstrip('"')
    start = text.find("{")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON in native completion")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="merged_work_order_specs.csv")
    ap.add_argument("--notes-col", default="其他注意事項")
    ap.add_argument("--wo-col", default="車床工單NO")
    ap.add_argument("--model", default="cnc-ecm:latest")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--limit", type=int, default=0, help="0 = all records")
    ap.add_argument("--out-jsonl", default="ecm_extractions_native.jsonl")
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()

    import pandas as pd
    df = pd.read_csv(args.csv)
    seen = set()
    rows = []
    for _, r in df.iterrows():
        wo = str(r.get(args.wo_col) or "").strip()
        note = r.get(args.notes_col)
        if not wo or wo in seen or not isinstance(note, str) or not note.strip():
            continue
        seen.add(wo)
        rows.append((wo, note.strip()))
    if args.limit:
        rows = rows[: args.limit]

    print(f"Native-prompt extraction | model={args.model} | {len(rows)} notes",
          file=sys.stderr)
    ok = fail = 0
    t0 = time.time()
    with Path(args.out_jsonl).open("w", encoding="utf-8") as fh:
        for i, (wo, note) in enumerate(rows, 1):
            try:
                completion = ollama_generate(args.host, args.model, note)
                obj = parse_native(completion)
                obj["work_order"] = wo
                obj["note"] = note
                fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
                ok += 1
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                print(f"  [{i}] {wo} FAILED: {msg[:110]}", file=sys.stderr)
                fh.write(json.dumps({"work_order": wo, "note": note,
                                     "_error": msg}, ensure_ascii=False) + "\n")
                fail += 1
            if i % 10 == 0 or i == len(rows):
                print(f"  ...{i}/{len(rows)} (ok={ok} fail={fail})",
                      file=sys.stderr)
            if args.sleep:
                time.sleep(args.sleep)
    dt = time.time() - t0
    print(f"Done in {dt:.1f}s. ok={ok} fail={fail} "
          f"(schema-conformance={ok/max(1,ok+fail):.3f})")
    print(f"  JSONL -> {args.out_jsonl}")


if __name__ == "__main__":
    main()
