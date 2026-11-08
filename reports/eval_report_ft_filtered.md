# ECM Extraction Evaluation Report

## Coverage

- Gold records loaded: **32**
- Pred records loaded: **215**
- Excluded work orders: ['G937', 'G948']
- Overlap (eval set size): **32**
- Gold-only (model missed entirely): 0
- Pred-only (no gold to score against): 183
- Pred-side schema/validation failures in JSONL: 0
- Gold-side error lines in JSONL: 0

## Entity extraction — STRICT (text + type exact)

### Per-entity-type

| Type | TP | FP | FN | P | R | F1 |
|------|----|----|----|---|---|----|
| Component | 97 | 48 | 78 | 0.669 | 0.554 | 0.606 |
| ExceptionTicket | 0 | 0 | 1 | 0.000 | 0.000 | 0.000 |
| Regulation | 4 | 1 | 2 | 0.800 | 0.667 | 0.727 |
| ResponsibleParty | 3 | 7 | 8 | 0.300 | 0.273 | 0.286 |
| Specification | 25 | 28 | 88 | 0.472 | 0.221 | 0.301 |
| **micro** | 129 | 84 | 177 | 0.606 | 0.422 | 0.497 |
| **macro** | - | - | - | 0.448 | 0.343 | 0.384 |

## Entity extraction — RELAXED (type + normalized form)

### Per-entity-type

| Type | TP | FP | FN | P | R | F1 |
|------|----|----|----|---|---|----|
| Component | 121 | 24 | 54 | 0.834 | 0.691 | 0.756 |
| ExceptionTicket | 0 | 0 | 1 | 0.000 | 0.000 | 0.000 |
| Regulation | 4 | 1 | 2 | 0.800 | 0.667 | 0.727 |
| ResponsibleParty | 4 | 6 | 7 | 0.400 | 0.364 | 0.381 |
| Specification | 36 | 17 | 77 | 0.679 | 0.319 | 0.434 |
| **micro** | 165 | 48 | 141 | 0.775 | 0.539 | 0.636 |
| **macro** | - | - | - | 0.543 | 0.408 | 0.460 |

## Change events (action exact, target substring match)

- TP=86  FP=59  FN=58
- **P=0.593  R=0.597  F1=0.595**

## Trace links (id + kind exact)

- TP=0  FP=12  FN=5
- **P=0.000  R=0.000  F1=0.000**

## Regulation hallucination check

- Closed vocabulary size: 17
- Total regulations extracted: 4
- Invalid (not in vocab): 0
- **Hallucination rate: 0.000**
