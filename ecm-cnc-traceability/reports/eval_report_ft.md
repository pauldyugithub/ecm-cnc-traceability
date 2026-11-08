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
| Component | 103 | 56 | 72 | 0.648 | 0.589 | 0.617 |
| ExceptionTicket | 0 | 0 | 1 | 0.000 | 0.000 | 0.000 |
| Regulation | 4 | 1 | 2 | 0.800 | 0.667 | 0.727 |
| ResponsibleParty | 3 | 7 | 8 | 0.300 | 0.273 | 0.286 |
| Specification | 31 | 63 | 82 | 0.330 | 0.274 | 0.300 |
| **micro** | 141 | 127 | 165 | 0.526 | 0.461 | 0.491 |
| **macro** | - | - | - | 0.416 | 0.360 | 0.386 |

## Entity extraction — RELAXED (type + normalized form)

### Per-entity-type

| Type | TP | FP | FN | P | R | F1 |
|------|----|----|----|---|---|----|
| Component | 133 | 26 | 42 | 0.836 | 0.760 | 0.796 |
| ExceptionTicket | 0 | 0 | 1 | 0.000 | 0.000 | 0.000 |
| Regulation | 4 | 1 | 2 | 0.800 | 0.667 | 0.727 |
| ResponsibleParty | 4 | 6 | 7 | 0.400 | 0.364 | 0.381 |
| Specification | 59 | 35 | 54 | 0.628 | 0.522 | 0.570 |
| **micro** | 200 | 68 | 106 | 0.746 | 0.654 | 0.697 |
| **macro** | - | - | - | 0.533 | 0.462 | 0.495 |

## Change events (action exact, target substring match)

- TP=86  FP=59  FN=58
- **P=0.593  R=0.597  F1=0.595**

## Trace links (id + kind exact)

- TP=0  FP=16  FN=5
- **P=0.000  R=0.000  F1=0.000**

## Regulation hallucination check

- Closed vocabulary size: 17
- Total regulations extracted: 37
- Invalid (not in vocab): 33
- **Hallucination rate: 0.892**

Examples of invalid regulation strings:
  - G901: `加拿大CSA規範`
  - G894: `CSA規範`
  - G886: `CSA規範`
  - G884: `CSA規範`
  - G883: `CSA規範`
  - G848: `CSA規範`
  - G889: `CSA規範`
  - G837: `越南電壓及相關電器標準`
  - G827: `CSA規範`
  - G812: `CSA標準`
