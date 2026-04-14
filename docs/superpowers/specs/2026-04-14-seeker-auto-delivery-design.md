# Seeker Auto-Delivery Design

**Date**: 2026-04-14
**Status**: Approved
**Scope**: Hub server + Provider client

## Problem

When a Seeker publishes a demand and goes offline before a Provider delivers the file, the matched demand stays in `status=matched` indefinitely. When the Seeker comes back online, no mechanism triggers re-delivery. Files sit in the Provider's `supply_provided/` directory, never reaching the Seeker.

## Solution Overview

Seeker calls `PATCH /status` (node_status="active") on startup. Hub queries matched-but-undelivered demands for that Seeker, then sends `wake_up_delivery` signals to the corresponding Providers. Providers auto-deliver files and confirm delivery back to Hub.

## Data Flow

```
Seeker PATCH /status (node_status="active", webhook_url="...")
  |
  +-- 1. Hub updates _agent_store[seeker_id].webhook_url
  |
  +-- 2. Hub queries repo.get_matched_demands_for_seeker(seeker_id)
  |     Returns demands where status='matched' AND seeker_id matches
  |
  +-- 3. For each matched demand:
  |     +-- Skip if status != 'matched' (avoid double-delivery)
  |     +-- Get Provider webhook_url from _agent_store[matched_agent_id]
  |     +-- Send POST {provider_url}/api/webhook/signal (async, fire-and-forget)
  |     |   payload: {action, demand_id, new_seeker_url, resource_type, match_token}
  |     +-- Append to delivery_tasks response
  |
  +-- 4. Return delivery_tasks to Seeker (informational)
  |
  +-- Provider receives wake_up signal:
        +-- Find local file matching resource_type in supply_provided/
        +-- P2PSender.send_file_to_seeker() delivers file
        +-- On success: POST /api/v1/task_completed to Hub
        +-- Hub marks demand status='delivered'
```

## Demand State Machine

```
pending  -->  matched  -->  delivered
                    \-->  failed
```

- `pending`: Created, waiting for Provider match
- `matched`: Provider found, delivery pending or in-progress
- `delivered`: File successfully delivered to Seeker
- `failed`: Delivery attempted but failed (timeout, Seeker offline again, etc.)

## Files to Modify (4 files)

### 1. `hub/hub_server/api/routes.py` — PATCH /status enhancement + new endpoint

**Current**: `update_agent_status` returns empty `delivery_tasks=[]` with a TODO comment.

**Changes**:
- After updating `_agent_store`, query `repo.get_matched_demands_for_seeker(agent_id)`
- For each matched demand where `matched_agent_id` has a known `webhook_url` in `_agent_store`:
  - Send async `wake_up_delivery` signal to Provider
  - Build `delivery_tasks` response list
- Return populated `delivery_tasks`

**New helper function**:
```python
async def _send_wake_up_to_provider(provider_url: str, demand: PendingDemand, seeker_webhook_url: str):
    """Send wake_up_delivery signal to Provider (fire-and-forget, non-blocking)."""
    import httpx
    payload = {
        "action": "wake_up_delivery",
        "demand_id": demand.demand_id,
        "new_seeker_url": seeker_webhook_url,
        "resource_type": demand.resource_type,
        "description": demand.description,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{provider_url}/api/webhook/signal", json=payload)
    except Exception:
        pass  # Provider offline - will retry on next sync
```

### 2. `hub/hub_server/services/lite_repository.py` — delivered state

**Current**: Only supports `pending`, `matched` states. `mark_matched()` exists.

**Changes**:
- Add `mark_delivered(demand_id: str)` method: sets `status='delivered'`
- Add `mark_failed(demand_id: str, error: str)` method: sets `status='failed'`, stores error info
- `find_matches()` already filters `WHERE status = 'pending'`, so delivered/failed demands won't re-match

### 3. `hub/client_sdk/webhook/server.py` — wake_up handler enhancement

**Current**: `receive_hub_signal` handler extracts `resource_type` by guessing from `demand_id` string (unreliable).

**Changes**:
- Accept `resource_type` directly from signal payload (fallback to old guess logic)
- Accept `description` from signal payload for better file matching
- After successful delivery, call Hub `POST /api/v1/task_completed` to mark demand as delivered
- Improve file matching: use `resource_type` + keyword matching from `description` instead of only extension

**Enhanced signal format**:
```json
{
    "action": "wake_up_delivery",
    "demand_id": "77dfc1c1-e116-4989-ae2f-5f3227380a2f",
    "new_seeker_url": "http://124.221.52.6:8899/api/webhook/delivery",
    "resource_type": "pdf",
    "description": "polymarket预测市场的可投资标的分析及跟踪内容--Daniel"
}
```

### 4. `hub/hub_server/api/routes.py` — new `/demand_status` endpoint

**Why needed**: The existing `POST /task_completed` requires a JWT `match_token` in `TaskCompletedRequest`. The Provider's wake_up handler does not have a match_token (it receives the signal from Hub, not from a direct match response). A lightweight endpoint avoids JWT contract mismatch.

```python
@router.put("/demand_status")
async def update_demand_status(payload: dict):
    """Update demand status (delivered/failed). Called by Provider after wake_up delivery."""
    demand_id = payload.get("demand_id")
    new_status = payload.get("status")  # "delivered" or "failed"
    repo = get_repository()
    if new_status == "delivered":
        repo.mark_delivered(demand_id)
    elif new_status == "failed":
        repo.mark_failed(demand_id, payload.get("error", ""))
    return {"status": "ok", "demand_id": demand_id, "new_status": new_status}
```

### 5. `hub/hub_server/services/lite_repository.py` — atomic mark_delivered

`mark_delivered` uses `UPDATE ... WHERE status = 'matched'` and checks `rowcount` to handle multi-provider race conditions:

```python
def mark_delivered(self, demand_id: str) -> bool:
    """Atomically mark demand as delivered. Returns False if already delivered."""
    with sqlite3.connect(self.db_path) as conn:
        cursor = conn.execute(
            "UPDATE pending_demands SET status = 'delivered' WHERE demand_id = ? AND status = 'matched'",
            (demand_id,)
        )
        return cursor.rowcount > 0
```

`mark_failed` is deferred — no caller triggers it in the current design. Add when retry logic is implemented.

### 6. `hub/client_sdk/webhook/server.py` — use deliver_file() + description matching

- Use `sender.deliver_file()` instead of `sender.send_file_to_seeker()` for automatic base64/stream/R2 strategy selection.
- Enhance `_find_file_for_demand_safe` to use description keywords as tiebreaker when multiple files match the extension.

**Post-delivery confirmation**:
```python
# After deliver_file() succeeds, call Hub's lightweight endpoint
async with httpx.AsyncClient(timeout=5.0) as client:
    await client.put(
        f"{HUB_URL}{API_V1_PREFIX}/demand_status",
        json={"demand_id": demand_id, "status": "delivered", "provider_id": provider_id}
    )
```

## Edge Cases

| Case | Handling |
|---|---|
| Provider offline when signal sent | Signal fails silently. Seeker gets `delivery_tasks` list. Provider's next `sync_supply_to_hub` will re-match and deliver. |
| demand already delivered | `get_matched_demands_for_seeker` only returns `status='matched'`, skipping delivered. |
| demand has no matched_agent_id | Skip (never matched, nothing to deliver). |
| Provider webhook_url unknown | Skip that demand, don't include in delivery_tasks. |
| Delivery fails (Seeker goes offline again) | Provider does NOT mark as delivered. Demand stays `matched`. Next Seeker online cycle retries. |
| Multiple Providers matched same demand | Each Provider gets wake_up signal. `mark_delivered` uses `WHERE status='matched'` — first UPDATE wins, subsequent get `rowcount=0` and skip. |

## What This Does NOT Cover

- Retry queue with exponential backoff (can be added later if needed)
- Seeker polling for delivery status (delivery_tasks response is informational only)
- Provider periodic polling for pending deliveries (existing `sync_supply_to_hub` covers cold-start)
- `mark_failed` state (deferred — no caller triggers it yet, add with retry logic)

- Retry queue with exponential backoff (can be added later if needed)
- Seeker polling for delivery status (delivery_tasks response is informational only)
- Provider periodic polling for pending deliveries (existing `sync_supply_to_hub` covers cold-start)

## Dependencies on Prior Fixes

This design builds on two prior fixes that must be deployed to the cloud Hub first:
1. `routes.py` — empty tags fallback in `create_pending_demand`
2. `lite_repository.py` — empty tags matching degradation in `find_matches`
