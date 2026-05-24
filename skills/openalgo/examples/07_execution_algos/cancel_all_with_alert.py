"""Bulk-cancel: cancel all open orders, alert the result.

Useful as a panic button or an end-of-day cleanup. Wraps
`cancelallorder` with a journal entry per cancelled order and a
summary alert.

Output folder: openalgo_workspace/execution_algos/cancel_all/
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.alerts import notify
from scripts.openalgo_client import default_strategy_tag, get_client
from scripts.trade_logger import open_journal

client = get_client()
strategy = default_strategy_tag()

workdir = Path("openalgo_workspace/execution_algos/cancel_all")
workdir.mkdir(parents=True, exist_ok=True)
journal = open_journal(workdir / f"journal_{datetime.now().strftime('%Y%m%d')}.csv")

mode = client.analyzerstatus().get("data", {}).get("mode", "unknown")
print(f"[{mode.upper()}]  about to cancel ALL open orders under strategy={strategy}")
if mode != "analyze":
    if input("Confirm cancel-all? [y/N] ").strip().lower() != "y":
        raise SystemExit("aborted")

resp = client.cancelallorder(strategy=strategy)
status = resp.get("status")
canceled = resp.get("canceled_orders", [])
failed = resp.get("failed_cancellations", [])

for oid in canceled:
    journal.write(strategy=strategy, event="cancelled", order_id=oid)
for oid in failed:
    journal.write(strategy=strategy, event="cancel_failed", order_id=oid)

msg = (
    f"[CANCEL ALL]\n"
    f"strategy:  {strategy}\n"
    f"status:    {status}\n"
    f"cancelled: {len(canceled)}\n"
    f"failed:    {len(failed)}\n"
    f"{resp.get('message', '')}"
)
print("\n" + msg)
notify(client, msg, via=("telegram",))
journal.close()
