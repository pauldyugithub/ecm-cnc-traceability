# ECM Extraction Evaluation Report

## Coverage

- Gold records loaded: **32**
- Pred records loaded: **32**
- Excluded work orders: ['G937', 'G948']
- Overlap (eval set size): **32**
- Gold-only (model missed entirely): 0
- Pred-only (no gold to score against): 0
- Pred-side schema/validation failures in JSONL: 0
- Gold-side error lines in JSONL: 0

## Entity extraction — STRICT (text + type exact)

### Per-entity-type

| Type | TP | FP | FN | P | R | F1 |
|------|----|----|----|---|---|----|
| Component | 91 | 65 | 84 | 0.583 | 0.520 | 0.550 |
| ExceptionTicket | 0 | 0 | 1 | 0.000 | 0.000 | 0.000 |
| Regulation | 3 | 0 | 3 | 1.000 | 0.500 | 0.667 |
| ResponsibleParty | 0 | 0 | 11 | 0.000 | 0.000 | 0.000 |
| Specification | 27 | 72 | 86 | 0.273 | 0.239 | 0.255 |
| work_order | 0 | 1 | 0 | 0.000 | 0.000 | 0.000 |
| **micro** | 121 | 138 | 185 | 0.467 | 0.395 | 0.428 |
| **macro** | - | - | - | 0.309 | 0.210 | 0.245 |

## Entity extraction — RELAXED (type + normalized form)

### Per-entity-type

| Type | TP | FP | FN | P | R | F1 |
|------|----|----|----|---|---|----|
| Component | 129 | 27 | 46 | 0.827 | 0.737 | 0.779 |
| ExceptionTicket | 0 | 0 | 1 | 0.000 | 0.000 | 0.000 |
| Regulation | 3 | 0 | 3 | 1.000 | 0.500 | 0.667 |
| ResponsibleParty | 0 | 0 | 11 | 0.000 | 0.000 | 0.000 |
| Specification | 62 | 37 | 51 | 0.626 | 0.549 | 0.585 |
| work_order | 0 | 1 | 0 | 0.000 | 0.000 | 0.000 |
| **micro** | 194 | 65 | 112 | 0.749 | 0.634 | 0.687 |
| **macro** | - | - | - | 0.409 | 0.298 | 0.339 |

## Change events (action exact, target substring match)

- TP=26  FP=59  FN=118
- **P=0.306  R=0.181  F1=0.227**

## Trace links (id + kind exact)

- TP=0  FP=3  FN=5
- **P=0.000  R=0.000  F1=0.000**

## Regulation hallucination check

- Closed vocabulary size: 17
- Total regulations extracted: 5
- Invalid (not in vocab): 4
- **Hallucination rate: 0.800**

Examples of invalid regulation strings:
  - G886: `CSA規範`
  - G889: `CSA規範`
  - G835: `越南電壓及相關電器標準`
  - G957: `UKCA`
