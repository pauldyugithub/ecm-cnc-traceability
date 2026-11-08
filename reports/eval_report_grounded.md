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
| Component | 98 | 61 | 77 | 0.616 | 0.560 | 0.587 |
| ExceptionTicket | 0 | 0 | 1 | 0.000 | 0.000 | 0.000 |
| Regulation | 2 | 0 | 4 | 1.000 | 0.333 | 0.500 |
| ResponsibleParty | 4 | 6 | 7 | 0.400 | 0.364 | 0.381 |
| Specification | 28 | 67 | 85 | 0.295 | 0.248 | 0.269 |
| **micro** | 132 | 134 | 174 | 0.496 | 0.431 | 0.462 |
| **macro** | - | - | - | 0.462 | 0.301 | 0.347 |

## Entity extraction — RELAXED (type + normalized form)

### Per-entity-type

| Type | TP | FP | FN | P | R | F1 |
|------|----|----|----|---|---|----|
| Component | 131 | 28 | 44 | 0.824 | 0.749 | 0.784 |
| ExceptionTicket | 0 | 0 | 1 | 0.000 | 0.000 | 0.000 |
| Regulation | 2 | 0 | 4 | 1.000 | 0.333 | 0.500 |
| ResponsibleParty | 6 | 4 | 5 | 0.600 | 0.545 | 0.571 |
| Specification | 55 | 40 | 58 | 0.579 | 0.487 | 0.529 |
| **micro** | 194 | 72 | 112 | 0.729 | 0.634 | 0.678 |
| **macro** | - | - | - | 0.601 | 0.423 | 0.477 |

## Change events (action exact, target substring match)

- TP=88  FP=55  FN=56
- **P=0.615  R=0.611  F1=0.613**

## Trace links (id + kind exact)

- TP=0  FP=4  FN=5
- **P=0.000  R=0.000  F1=0.000**

## Regulation hallucination check

- Closed vocabulary size: 17
- Total regulations extracted: 24
- Invalid (not in vocab): 23
- **Hallucination rate: 0.958**

Examples of invalid regulation strings:
  - G848: `CSA規範`
  - G837: `越南電壓及相關電器標準`
  - G769: `CE規範`
  - G768: `CE規範`
  - G830: `CSA規範`
  - G812: `CSA標準`
  - G887: `CSA規範`
  - G838: `英國相關電器標準`
  - G838: `CE認證`
  - G958: `越南電壓及相關電器標準`
