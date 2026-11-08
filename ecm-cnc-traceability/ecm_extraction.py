#!/usr/bin/env python3
"""
ECM (Engineering Change Management) information-extraction baseline.

Multi-provider version. Same Pydantic schema, same few-shot prompt, same
output JSONL — only the LLM backend swaps. This means evaluate_ecm.py does
not need to change, and a multi-model comparison table is just a shell loop:

    for p in anthropic openai local; do
        python ecm_extraction.py --csv merged_work_order_specs.csv --provider $p
    done

Providers
---------
  anthropic : Anthropic Messages API (default model: claude-sonnet-4-20250514)
  openai    : OpenAI Chat Completions API (default model: gpt-4o-mini)
  local     : Any OpenAI-compatible local server (vLLM, Ollama, llama.cpp,
              LM Studio). Defaults to http://localhost:8000/v1 (vLLM).
              You MUST pass --model for local; no universal default exists.

Env vars
--------
  ANTHROPIC_API_KEY   required for --provider anthropic
  OPENAI_API_KEY      required for --provider openai
                      optional for --provider local (a placeholder is used
                      if unset, since most local servers ignore the key)

Install
-------
    pip install pydantic pandas
    pip install anthropic                  # only if using --provider anthropic
    pip install openai                     # for openai OR local

Usage
-----
    python ecm_extraction.py --csv merged_work_order_specs.csv --limit 20
    python ecm_extraction.py --csv merged_work_order_specs.csv \\
        --provider openai --model gpt-4o-mini
    python ecm_extraction.py --csv merged_work_order_specs.csv \\
        --provider local --model Qwen/Qwen2.5-7B-Instruct \\
        --base-url http://localhost:8000/v1

Output files are named with the provider so multiple runs don't collide:
    ecm_extractions_<provider>.jsonl
    ecm_extractions_<provider>_flat.csv

Notes
-----
  - ~125/217 notes are truncated at 255 chars in the source ACCESS export.
    Recover full text from the original DB before drawing strong conclusions.
  - Two SYNTHETIC exemplars are baked in as few-shot anchors (public release); exclude
    them from any evaluation set (evaluate_ecm.py does this by default).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from enum import Enum
from typing import Optional

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

# --------------------------------------------------------------------------- #
# STEP 1: SCHEMA (unchanged — provider-agnostic)
# --------------------------------------------------------------------------- #


class ChangeAction(str, Enum):
    ADD = "add"
    MODIFY = "modify"
    REMOVE = "remove"
    REQUIRE = "require"
    OTHER = "other"


class EntityType(str, Enum):
    COMPONENT = "component"
    SPEC_VALUE = "spec_value"
    REGULATION = "regulation"
    BRANDING = "branding"
    DATE = "date"
    TRACE_ID = "trace_id"
    OTHER = "other"


class Entity(BaseModel):
    text: str = Field(..., description="Verbatim span from the note.")
    # v2 (IJAMT revision): accept any type string at ingest; the evolved
    # taxonomy (Component/Specification/Regulation/ExceptionTicket/
    # ResponsibleParty) is canonicalized case-/alias-insensitively at
    # scoring time. Structural validity = fields and shapes, not vocabulary.
    type: str = Field(..., description="Entity category.")
    normalized: Optional[str] = Field(
        None,
        description="Optional canonical form, e.g. '中心高=490mm' or 'model:LA43->LA38'.",
    )


class ChangeEvent(BaseModel):
    action: str  # open at ingest; canonicalized/casefolded at scoring time
    target: str = Field(..., description="The component/spec the action applies to.")
    detail: Optional[str] = Field(
        None, description="From/to values, conditions, or qualifiers if present."
    )
    triggered_by: Optional[str] = Field(
        None,
        description="Trace ID that caused this change if stated (e.g. QI-00001).",
    )


class TraceLink(BaseModel):
    id: str = Field(..., description="The reference string, e.g. QI-00001, B-000001, O900.")
    kind: str = Field(
        ..., description="One of: exception_ticket, sales_order, original_work_order, other."
    )


class NoteExtraction(BaseModel):
    work_order: Optional[str] = Field(None, description="Work order NO, passed in from the row.")
    change_date: Optional[str] = Field(None, description="Most recent change-log date if any.")
    entities: list[Entity] = Field(default_factory=list)
    change_events: list[ChangeEvent] = Field(default_factory=list)
    trace_links: list[TraceLink] = Field(default_factory=list)
    regulations: list[str] = Field(
        default_factory=list, description="Distinct regulatory standards mentioned (UL/CSA/CE...)."
    )
    summary_en: Optional[str] = Field(
        None, description="One-sentence English summary of the change order."
    )


# --------------------------------------------------------------------------- #
# STEP 3: FEW-SHOT PROMPT (unchanged — provider-agnostic)
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """You are an information-extraction system for CNC lathe \
engineering-change notes written in mixed Traditional Chinese and English. \
Extract entities, change events, traceability links, and regulations into the \
requested JSON schema. Return ONLY a single JSON object, no markdown, no \
preamble. If a field is unknown, use null or an empty list. Keep 'text' spans \
verbatim from the note."""

FEWSHOT = [
    # NOTE (public release): the two original exemplar annotations (work
    # orders G937, G948) are part of the manufacturer's proprietary corpus
    # and are available with the on-request gold subset (see README).
    # The entries below are SYNTHETIC illustrative exemplars with the same
    # structure, bilingual style, and schema coverage; identifiers are fake.
    {
        "note": (
            "2022/01/10新增事項\n"
            "1.原尾座心軸型式為手動，依客戶加工需求修改為電動\n"
            "異常單號為QI-00001，業務轉開單號為 B-000001\n"
            "2. 參照前單 O900 加裝光學尺"
        ),
        "json": {
            "work_order": "O901",
            "entities": [
                {"text": "尾座心軸", "type": "component"},
                {"text": "光學尺", "type": "component"},
            ],
            "change_events": [
                {"action": "modify", "target": "尾座心軸",
                 "detail": "手動改電動", "triggered_by": "客戶加工需求"},
                {"action": "add", "target": "光學尺", "detail": None,
                 "triggered_by": None},
            ],
            "trace_links": [
                {"id": "QI-00001", "kind": "exception_ticket"},
                {"id": "B-000001", "kind": "sales_order"},
                {"id": "O900", "kind": "original_work_order"},
            ],
            "regulations": [],
        },
    },
    {
        "note": (
            "1. 機器出口歐洲，需符合CE規範\n"
            "2. 主軸馬達由 15KW 加大為 22KW\n"
            "3. 夾頭數量由 1PCS 改為 2PCS"
        ),
        "json": {
            "work_order": "O902",
            "entities": [
                {"text": "主軸馬達", "type": "component"},
                {"text": "22KW", "type": "spec_value"},
                {"text": "CE", "type": "regulation"},
                {"text": "夾頭", "type": "component"},
            ],
            "change_events": [
                {"action": "modify", "target": "主軸馬達",
                 "detail": "15KW -> 22KW", "triggered_by": "出口歐洲"},
                {"action": "modify", "target": "夾頭",
                 "detail": "1PCS -> 2PCS", "triggered_by": None},
            ],
            "trace_links": [],
            "regulations": ["CE"],
        },
    },
]


def build_messages(note: str, work_order: Optional[str]) -> list[dict]:
    """Assemble user/assistant turns for one note. System prompt is added by the
    provider layer (Anthropic takes it as a separate field; OpenAI takes it as
    the first message). This function stays provider-agnostic."""
    msgs: list[dict] = []
    for ex in FEWSHOT:
        msgs.append({"role": "user", "content": f"NOTE:\n{ex['note']}"})
        msgs.append({"role": "assistant", "content": json.dumps(ex["json"], ensure_ascii=False)})
    wo_hint = f"(work_order = {work_order})\n" if work_order else ""
    msgs.append({"role": "user", "content": f"{wo_hint}NOTE:\n{note}"})
    return msgs


# --------------------------------------------------------------------------- #
# Provider abstraction
# --------------------------------------------------------------------------- #

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o-mini",
    "local": None,                # user must pass --model
}


class LLMClient:
    """Thin wrapper. Returns plain text; JSON parsing happens in extract_one."""

    def __init__(self, provider: str, model: str, base_url: Optional[str] = None,
                 temperature: float = 0.0):
        self.provider = provider
        self.model = model
        self.temperature = temperature  # 0.0 = greedy / near-deterministic, recommended for IE

        if provider == "anthropic":
            try:
                from anthropic import Anthropic
            except ImportError:
                sys.exit("pip install anthropic")
            self.client = Anthropic()

        elif provider in ("openai", "local"):
            try:
                from openai import OpenAI
            except ImportError:
                sys.exit("pip install openai")
            kwargs = {}
            if provider == "local":
                kwargs["base_url"] = base_url or "http://localhost:8000/v1"
                # Most local servers ignore the key; OpenAI SDK requires *some* value.
                kwargs["api_key"] = os.environ.get("OPENAI_API_KEY", "local-placeholder")
            self.client = OpenAI(**kwargs)

        else:
            raise ValueError(f"Unknown provider: {provider}")

    def call(self, system: str, messages: list[dict], max_tokens: int = 1500) -> str:
        if self.provider == "anthropic":
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=self.temperature,
                system=system,
                messages=messages,
            )
            return "".join(b.text for b in resp.content if b.type == "text").strip()

        # OpenAI-style (works for both --provider openai and --provider local
        # when the local server is OpenAI-compatible: vLLM, Ollama, LM Studio, ...)
        full = [{"role": "system", "content": system}] + messages
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=self.temperature,
            messages=full,
        )
        return (resp.choices[0].message.content or "").strip()


# --------------------------------------------------------------------------- #
# Extraction + validation
# --------------------------------------------------------------------------- #

def extract_one(client: LLMClient, note: str, work_order: Optional[str]) -> dict:
    """Call the model, parse + validate JSON. Returns a dict with status."""
    raw = ""
    try:
        raw = client.call(SYSTEM_PROMPT, build_messages(note, work_order))
        # Strip accidental code fences (some models wrap JSON in ```json ... ```).
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.lstrip().lower().startswith("json"):
                raw = raw.lstrip()[4:]
            raw = raw.strip("` \n")
        data = json.loads(raw)
        if work_order and not data.get("work_order"):
            data["work_order"] = work_order
        validated = NoteExtraction.model_validate(data)
        return {"ok": True, "data": validated.model_dump(), "raw": raw}
    except (json.JSONDecodeError, ValidationError) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "raw": raw}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "raw": raw}


def flatten_for_csv(rec: dict) -> dict:
    return {
        "work_order": rec.get("work_order"),
        "change_date": rec.get("change_date"),
        "n_entities": len(rec.get("entities") or []),
        "n_change_events": len(rec.get("change_events") or []),
        "n_trace_links": len(rec.get("trace_links") or []),
        "regulations": "|".join(rec.get("regulations") or []),
        "trace_ids": "|".join(t["id"] for t in rec.get("trace_links") or []),
        "actions": "|".join(c["action"] for c in rec.get("change_events") or []),
        "summary_en": rec.get("summary_en"),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def check_env(provider: str) -> None:
    if provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY in your environment first.")
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        sys.exit("Set OPENAI_API_KEY in your environment first.")
    # local: no key check; the local server may or may not need one.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="merged_work_order_specs.csv")
    ap.add_argument("--notes-col", default="其他注意事項")
    ap.add_argument("--wo-col", default="車床工單NO")
    ap.add_argument("--provider", choices=["anthropic", "openai", "local"],
                    default="anthropic",
                    help="Which LLM backend to use.")
    ap.add_argument("--model", default=None,
                    help="Model name. If omitted, a per-provider default is used "
                         "(local has no default — you must pass one).")
    ap.add_argument("--base-url", default=None,
                    help="Base URL for --provider local "
                         "(default http://localhost:8000/v1, i.e. vLLM).")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="Sampling temperature (default 0.0 for IE reproducibility). "
                         "Anthropic accepts 0.0-1.0; OpenAI 0.0-2.0; local servers vary.")
    ap.add_argument("--limit", type=int, default=0, help="0 = all records")
    ap.add_argument("--out-jsonl", default=None,
                    help="Default: ecm_extractions_<provider>.jsonl")
    ap.add_argument("--out-csv", default=None,
                    help="Default: ecm_extractions_<provider>_flat.csv")
    ap.add_argument("--sleep", type=float, default=0.3,
                    help="pause between calls (s). Set 0 for local.")
    args = ap.parse_args()

    check_env(args.provider)
    model = args.model or DEFAULT_MODELS[args.provider]
    if model is None:
        sys.exit("--provider local requires --model "
                 "(e.g. --model Qwen/Qwen2.5-7B-Instruct).")

    out_jsonl = args.out_jsonl or f"ecm_extractions_{args.provider}.jsonl"
    out_csv = args.out_csv or f"ecm_extractions_{args.provider}_flat.csv"

    client = LLMClient(args.provider, model, base_url=args.base_url,
                       temperature=args.temperature)

    df = pd.read_csv(args.csv)
    sub = df[[args.wo_col, args.notes_col]].dropna(subset=[args.notes_col])
    if args.limit:
        sub = sub.head(args.limit)
    print(f"Provider={args.provider}  Model={model}  Temperature={args.temperature}",
          file=sys.stderr)
    print(f"Processing {len(sub)} notes ...", file=sys.stderr)

    flat_rows, n_ok, n_fail = [], 0, 0
    t0 = time.time()
    with open(out_jsonl, "w", encoding="utf-8") as fh:
        for i, (_, row) in enumerate(sub.iterrows(), 1):
            wo = str(row[args.wo_col])
            note = str(row[args.notes_col])
            res = extract_one(client, note, wo)
            if res["ok"]:
                n_ok += 1
                fh.write(json.dumps(res["data"], ensure_ascii=False) + "\n")
                flat_rows.append(flatten_for_csv(res["data"]))
            else:
                n_fail += 1
                fh.write(json.dumps(
                    {"work_order": wo, "_error": res["error"]},
                    ensure_ascii=False,
                ) + "\n")
                print(f"  [{i}] {wo} FAILED: {res['error'][:140]}", file=sys.stderr)
            if i % 10 == 0:
                print(f"  ...{i}/{len(sub)} (ok={n_ok} fail={n_fail})", file=sys.stderr)
            if args.sleep > 0:
                time.sleep(args.sleep)

    pd.DataFrame(flat_rows).to_csv(out_csv, index=False, encoding="utf-8-sig")
    dt = time.time() - t0
    conform = n_ok / max(n_ok + n_fail, 1)
    print(f"\nDone in {dt:.1f}s. ok={n_ok} fail={n_fail} "
          f"(schema-conformance={conform:.3f})", file=sys.stderr)
    print(f"  JSONL    -> {out_jsonl}", file=sys.stderr)
    print(f"  flat CSV -> {out_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
