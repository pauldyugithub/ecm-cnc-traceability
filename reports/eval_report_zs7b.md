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
| Component | 49 | 92 | 126 | 0.348 | 0.280 | 0.310 |
| ExceptionTicket | 0 | 0 | 1 | 0.000 | 0.000 | 0.000 |
| Regulation | 3 | 2 | 3 | 0.600 | 0.500 | 0.545 |
| ResponsibleParty | 5 | 4 | 6 | 0.556 | 0.455 | 0.500 |
| Specification | 13 | 33 | 100 | 0.283 | 0.115 | 0.164 |
| **micro** | 70 | 131 | 236 | 0.348 | 0.229 | 0.276 |
| **macro** | - | - | - | 0.357 | 0.270 | 0.304 |

## Entity extraction — RELAXED (type + normalized form)

### Per-entity-type

| Type | TP | FP | FN | P | R | F1 |
|------|----|----|----|---|---|----|
| Component | 92 | 49 | 83 | 0.652 | 0.526 | 0.582 |
| ExceptionTicket | 0 | 0 | 1 | 0.000 | 0.000 | 0.000 |
| Regulation | 5 | 0 | 1 | 1.000 | 0.833 | 0.909 |
| ResponsibleParty | 7 | 2 | 4 | 0.778 | 0.636 | 0.700 |
| Specification | 35 | 11 | 78 | 0.761 | 0.310 | 0.440 |
| **micro** | 139 | 62 | 167 | 0.692 | 0.454 | 0.548 |
| **macro** | - | - | - | 0.638 | 0.461 | 0.526 |

## Change events (action exact, target substring match)

- TP=31  FP=59  FN=113
- **P=0.344  R=0.215  F1=0.265**

## Trace links (id + kind exact)

- TP=0  FP=3  FN=5
- **P=0.000  R=0.000  F1=0.000**

## Regulation hallucination check

- Closed vocabulary size: 17
- Total regulations extracted: 16
- Invalid (not in vocab): 15
- **Hallucination rate: 0.938**

Examples of invalid regulation strings:
  - G886: `英制標準`
  - G886: `CSA規範`
  - G889: `英制標準`
  - G889: `CSA規範`
  - G716: `床身無凹口`
  - G716: `X軸和船座均是使用公制, Z軸使用公制`
  - G863: `須符合越南電壓及相關電器標準`
  - G863: `兩心間距在沒有卡盤與頂針的狀態下為2200mm，實際加工距離為2000mm`
  - G835: `越南電壓及相關電器標準`
  - G693: `機台鈑金全部裝上去，在台灣試車完成後,整機出口`
