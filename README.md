# ECM Traceability Extraction from Legacy CNC Work Orders

Schema, tooling, and evaluation harness for the IJAMT manuscript
*"Recovering Engineering-Change Traceability from Legacy CNC Work Orders:
A Pydantic Schema and Fine-Tuned Small Language Model Baseline."*

Every number in the paper is reproducible from the commands in
`REPRODUCE.md`, run deterministically at temperature 0 with fixed seeds.

## What is open and what is restricted

| Artifact | Status |
|---|---|
| Pydantic extraction schema (`ecm_extraction.py`) | **MIT, included** |
| Native-prompt extraction runner (`ecm_extract_native.py`) | **MIT, included** |
| Format normalizer (`gold_to_eval.py`) | **MIT, included** |
| Evaluation harness: bootstrap CIs, truncation strata, link-error taxonomy (`evaluate_ecm.py`) | **MIT, included** |
| Attestation filter (`apply_attestation.py`) | **MIT, included** |
| Comparison baselines: rules / zero-shot / few-shot (`ecm_baselines.py`) | **MIT, included** |
| Fine-tuned model's training-time system prompt + template (`Modelfile.txt`) | **Included** (prompt text only) |
| Evaluation reports of the documented run (`reports/`) | **Included** |
| Raw 399-work-order corpus (`merged_work_order_specs.csv`) | **Restricted** — proprietary to the manufacturer; not released |
| 32-record gold evaluation set | **On request** — from the corresponding author, after the manufacturer's de-identification review |
| Fine-tuned model weights | **Not released** — trained on proprietary text |

## Quick start

```bash
pip install pydantic pandas openai
# score any prediction file against a gold file:
python gold_to_eval.py --in your_predictions.jsonl --out pred.jsonl
python evaluate_ecm.py --gold gold_eval.jsonl --pred pred.jsonl \
    --exclude G937,G948 --bootstrap 2000 --stratify-truncation \
    --link-errors link_errors.csv
```

## Citation

Please cite the IJAMT paper (reference to be added upon publication).
