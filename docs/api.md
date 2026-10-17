# MuleTrace API

> **Outdated (pre-hardening).** Decisions are now PASS / FLAG / HOLD, write endpoints may need `X-MuleTrace-Token`, and responses include `explanations`, `simulated` and `recommendation`. See the API section of the README and the live schema at `/docs`.

MuleTrace is a FastAPI application that detects suspicious money movement and potential money-laundering activity. It scores payments in real time and assigns one of three decisions: `ALLOW`, `REVIEW`, or `HOLD`. Each decision includes simple explanations to help analysts understand the risk.

All requests and responses use JSON. The sample data shows an average scoring time of approximately 1.5 milliseconds per payment.

## All Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Checks whether the application is running |
| GET | `/system` | Returns system information, including IBM Z details |
| POST | `/score` | Scores a payment and returns a risk decision |
| GET | `/alerts` | Lists flagged payments |
| POST | `/alerts/{id}/action` | Confirms, dismisses, or escalates an alert |
| GET | `/graph/{account}` | Returns money-flow information for an account |
| GET | `/stats` | Returns scoring statistics and average decision time |

---

## 1. GET /health

**What it does:** Checks whether the MuleTrace application is running.

**Example request**

```http
GET /health
```

**Example response**

```json
{
  "status": "ok"
}
```

## 2. GET /system

**What it does:** Returns information about the system running MuleTrace. The sample reports the `s390x` architecture, which is associated with IBM Z systems. The `nnpa` field indicates whether the AI accelerator is available, and `data_egress` describes the reported data-egress setting.

**Example request**

```http
GET /system
```

**Example response**

```json
{
  "arch": "s390x",
  "byteorder": "big",
  "python": "3.12.3",
  "nnpa": true,
  "machine_type": "9175",
  "data_egress": "none"
}
```

## 3. POST /score

**What it does:** Accepts one payment, calculates its risk score, and returns a decision.

A higher score indicates higher risk. The decision can be `ALLOW`, `REVIEW`, or `HOLD`.

**Request fields**

| Field | Description |
|---|---|
| `txn_id` | Unique payment transaction ID |
| `ts` | Payment timestamp |
| `src` | Sending account ID |
| `dst` | Receiving account ID |
| `amount` | Payment amount |
| `currency` | Sender-side currency |
| `cur_recv` | Receiver-side currency |
| `fmt` | Payment format, such as `ACH` |

**Example request**

```http
POST /score
Content-Type: application/json
```

```json
{
  "txn_id": "1602413",
  "ts": 27702199,
  "src": "021745_803366440",
  "dst": "0021615_8036AE1C0",
  "amount": 43038.53,
  "currency": "US Dollar",
  "cur_recv": "US Dollar",
  "fmt": "ACH"
}
```

**Example response**

```json
{
  "score": 0.9929794669151306,
  "decision": "HOLD",
  "reasons": [
    "Sender is passing on 100% of money it received 0 min ago"
  ],
  "latency_ms": 1.4
}
```

The response contains the risk score, decision, explanation list, and processing time in milliseconds.

## 4. GET /alerts

**What it does:** Returns flagged payments, usually those assigned `REVIEW` or `HOLD`. The sample documentation describes alerts ordered by risk score, highest first.

**Example request**

```http
GET /alerts
```

**Example response**

```json
[
  {
    "id": 11,
    "txn_id": "1600931",
    "ts": 27702196,
    "src": "0210575_806A8FB00",
    "dst": "0215841_80F1BB2B0",
    "amount": 1292091.71,
    "score": 0.9957350492477417,
    "decision": "HOLD",
    "reasons": [
      "Sender is passing on 100% of money it received 0 min ago"
    ],
    "status": "open",
    "truth": 0
  },
  {
    "id": 13,
    "txn_id": "1600993",
    "ts": 27702196,
    "src": "070_1004286A8",
    "dst": "01490_8019BD7D0",
    "amount": 5215.78,
    "score": 0.9572904706001282,
    "decision": "REVIEW",
    "reasons": [
      "Sender is passing on 100% of money it received 4 min ago",
      "Sender paid 413 different accounts in the last hour"
    ],
    "status": "open",
    "truth": 0
  }
]
```

**Important fields**

- `id`: Alert ID used to perform an action.
- `score`: Payment risk score.
- `decision`: `REVIEW` or `HOLD`.
- `reasons`: Explanations for the alert.
- `status`: Current alert status.
- `truth`: Test-data label, if provided. It is intended for evaluation and not necessarily available in production.

## 5. POST /alerts/{id}/action

**What it does:** Records an analyst's action for a specific alert.

Replace `{id}` with the alert ID returned by `/alerts`.

**Supported actions**

- `confirm`: Confirm the alert as genuine suspicious activity.
- `dismiss`: Dismiss the alert as a false positive.
- `escalate`: Send the alert to a senior analyst.

**Example request**

```http
POST /alerts/13/action
Content-Type: application/json
```

```json
{
  "action": "escalate"
}
```

**Example response**

```json
{
  "id": 13,
  "action": "escalate",
  "status": "escalated"
}
```

An invalid alert ID or unsupported action should return an appropriate error response.

## 6. GET /graph/{account}

**What it does:** Returns the money-flow graph around a specific account. It can show accounts that sent money to the selected account and accounts that received money from it.

**Path parameter**

| Parameter | Description |
|---|---|
| `account` | Account ID to investigate |

**Example request**

```http
GET /graph/070_1004286A8
```

**Example response**

```json
{
  "nodes": [
    {
      "id": "070_1004286A8",
      "role": "focus"
    },
    {
      "id": "034943_807BC2340",
      "role": "sender"
    },
    {
      "id": "01547_800E3A290",
      "role": "receiver"
    },
    {
      "id": "005425_802186300",
      "role": "receiver"
    }
  ],
  "edges": [
    {
      "from": "034943_807BC2340",
      "to": "070_1004286A8",
      "amount": 648.72,
      "t": 27702140
    },
    {
      "from": "070_1004286A8",
      "to": "01547_800E3A290",
      "amount": 1810.77,
      "t": 27702139
    },
    {
      "from": "070_1004286A8",
      "to": "005425_802186300",
      "amount": 2470.56,
      "t": 27702139
    }
  ]
}
```

The `nodes` array contains accounts. The `edges` array contains payment connections, amounts, and timestamps.

## 7. GET /stats

**What it does:** Returns statistics about processed payments and scoring performance.

**Example request**

```http
GET /stats
```

**Example response**

```json
{
  "scored": 3000,
  "review": 24,
  "hold": 4,
  "ms_total": 4564.28318399503,
  "avg_ms": 1.52
}
```

**Response fields**

| Field | Description |
|---|---|
| `scored` | Total number of payments scored |
| `review` | Number of payments assigned `REVIEW` |
| `hold` | Number of payments assigned `HOLD` |
| `ms_total` | Total decision-processing time in milliseconds |
| `avg_ms` | Average decision time per payment in milliseconds |

---

## Notes

- All endpoints return or accept JSON where applicable.
- `ALLOW`, `REVIEW`, and `HOLD` describe payment-scoring decisions.
- Alert actions allow analysts to record a follow-up decision.
- Example values are based on the supplied sample data and illustrate the documented response formats.
- This document describes the API contract; actual behavior should be verified against the running FastAPI application.
