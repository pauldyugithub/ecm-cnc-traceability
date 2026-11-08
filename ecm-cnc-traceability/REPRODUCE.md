# Reproducing every number in the paper

```bash
# 0. Convert the verified gold worksheet to canonical scoring format
python gold_to_eval.py --in gold_worksheet_verified.jsonl \
    --out gold_eval.jsonl --append-exemplars

# 1. Fine-tuned extraction under the model's own training prompt (217 notes)
python ecm_extract_native.py --csv merged_work_order_specs.csv \
    --model cnc-ecm:latest --out-jsonl ecm_extractions_native.jsonl
python gold_to_eval.py --in ecm_extractions_native.jsonl --out pred_ft_eval.jsonl

# 2. Baseline-variant evaluation (CIs, truncation strata, link taxonomy)
python evaluate_ecm.py --gold gold_eval.jsonl --pred pred_ft_eval.jsonl \
    --exclude G937,G948 --bootstrap 2000 --stratify-truncation \
    --link-errors link_errors_ft.csv --report eval_report_ft.md

# 3. Attestation filter + filtered-variant evaluation
python apply_attestation.py --in pred_ft_eval.jsonl --out pred_ft_filtered.jsonl
python evaluate_ecm.py --gold gold_eval.jsonl --pred pred_ft_filtered.jsonl \
    --exclude G937,G948 --bootstrap 2000 --stratify-truncation \
    --link-errors link_errors_ft_filtered.csv --report eval_report_ft_filtered.md

# 4. Grounded ablation arm (Modelfile variant of the same weights)
python ecm_extract_native.py --csv merged_work_order_specs.csv \
    --model cnc-ecm-grounded:latest --out-jsonl ecm_extractions_grounded.jsonl
python gold_to_eval.py --in ecm_extractions_grounded.jsonl --out pred_g_eval.jsonl
python evaluate_ecm.py --gold gold_eval.jsonl --pred pred_g_eval.jsonl \
    --exclude G937,G948 --bootstrap 2000 --report eval_report_grounded.md

# 5. Comparison baselines, scored under the identical protocol
python ecm_baselines.py --mode rules    --gold gold_eval.jsonl --tag rules
python ecm_baselines.py --mode zeroshot --gold gold_eval.jsonl \
    --base-url http://localhost:11434/v1 --model qwen2.5:7b-instruct --tag zs7b
python ecm_baselines.py --mode fewshot  --gold gold_eval.jsonl \
    --base-url http://localhost:11434/v1 --model qwen2.5:7b-instruct \
    --exemplars G937,G948 --tag fs7b
for t in rules zs7b fs7b; do
  python gold_to_eval.py --in ecm_extractions_$t.jsonl --out pred_$t.jsonl
  python evaluate_ecm.py --gold gold_eval.jsonl --pred pred_$t.jsonl \
      --exclude G937,G948 --bootstrap 2000 --report eval_report_$t.md
done
```

All commands are deterministic (temperature 0, fixed seeds). Gold and
prediction JSONL files contain proprietary annotation text and are not in
this repository; the gold evaluation subset is available from the
corresponding author on request (see README).
