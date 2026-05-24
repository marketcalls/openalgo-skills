# Alerts — Telegram + WhatsApp Reference

OpenAlgo ships two send-only alert endpoints. Both are designed for
**outbound** notifications from a strategy — order placed, fill, SL hit,
P&L summary, scanner result. They are not bidirectional messaging
channels in the SDK (though WhatsApp supports slash-command receiving
on the user's *own* number via the `/whatsapp` web UI — see
[Receiving WhatsApp commands](#receiving-whatsapp-commands)).

| Channel | Method | Supports text | Supports image | Supports document | Multi-recipient |
|---------|--------|:------:|:------:|:------:|:------:|
| Telegram | `client.telegram(username, message)` | yes | no | no | no (one openalgo user) |
| WhatsApp | `client.whatsapp(text, to=..., image=..., document=...)` | yes | **yes** | **yes** | yes (up to 5) |

For rich formatted alerts always go through [`scripts/alerts.py`](../scripts/alerts.py) — it ships pre-built templates and a single `notify(...)` call that fans out to both channels.

---

## Telegram — `client.telegram`

### Setup

1. Open `/telegram` in the OpenAlgo web UI.
2. Bind your Telegram username to your OpenAlgo login (one-time).
3. Add your username to `.env`:
   ```
   ALERT_TELEGRAM_USERNAME=your_openalgo_login_id
   ```

### Request

```python
client.telegram(
    username="<openalgo_loginid>",
    message="NIFTY crossed 26000",
)
```

### Success Response

```json
{ "status": "success", "message": "Notification sent successfully" }
```

### Read these fields

| Field | Used for |
|-------|----------|
| `status` | success / failure gate |
| `message` | human-readable diagnostic on failure (token expired, user not bound, etc.) |

Telegram has no rate cost in the OpenAlgo rate-limit policy, but the Telegram Bot API itself caps ~30 msg/sec/bot. Use `notify(..., via=("telegram",))` if you want to send hundreds of alerts during a market open.

---

## WhatsApp — `client.whatsapp`

The most capable alert surface. One call handles every common shape:
text, image with caption, document with filename, self-send, single
recipient, small broadcast.

### Setup

1. Open `/whatsapp` in the OpenAlgo web UI.
2. Click **Pair**, scan the QR with your phone.
3. Pairing is admin-only — a leaked API key cannot re-pair the device.
4. Once paired the bot auto-reconnects on every server boot from the
   encrypted session blob stored in `openalgo.db`.

Optional `.env` defaults:

```
ALERT_WHATSAPP_TO=919876543210
# or comma-separated for a broadcast
ALERT_WHATSAPP_TO=919876543210,919812345678
```

### Request — Send to yourself (simplest case)

```python
client.whatsapp("NIFTY crossed 26000")
```

When neither `to` nor `username` is given, the message goes to the
paired number's **"Message yourself"** chat.

### Request — Single recipient

```python
client.whatsapp(
    "Order placed: BUY RELIANCE x 10 @ MARKET",
    to="919876543210",
)
```

### Request — Broadcast (up to 5)

```python
client.whatsapp(
    "Server maintenance starting in 10 minutes",
    to=["919876543210", "919812345678", "919900112233"],
)
```

### Request — Image with caption

The file must live under `WHATSAPP_ATTACHMENT_ROOTS` on the OpenAlgo
server (default `<openalgo>/db/attachments/`).

```python
client.whatsapp(
    to="919876543210",
    image="/srv/charts/nifty_eod.png",
    caption="NIFTY end-of-day chart",
)
```

### Request — Document (PDF, CSV)

```python
client.whatsapp(
    "Daily P&L report attached.",
    to="919876543210",
    document="/srv/reports/2026-05-24.pdf",
    filename="DailyPnL.pdf",
)
```

### Request — Fire-and-forget (skip delivery report)

```python
client.whatsapp("Stop-loss hit on BANKNIFTY", wait_for_delivery=False)
```

Saves ~1 second when you do not need the per-recipient delivery list.

### Request — Send to a linked OpenAlgo user (legacy path)

```python
client.whatsapp(
    "Position update: BANKNIFTY 48000 CE now at +21% P&L.",
    username="alice",       # OpenAlgo login id of a linked user
)
```

### Success Response (`wait_for_delivery=True`, default)

```json
{
  "status": "success",
  "message": "Delivered to 1, failed 0",
  "data": {
    "sent":    ["<self>"],
    "failed":  [],
    "skipped": 0
  }
}
```

### Read these fields

| Field | Used for |
|-------|----------|
| `status` | `responses.ensure_success(resp)` gate |
| `data.sent[]` | recipients confirmed delivered |
| `data.failed[]` | recipients that did not get the message — retry candidates |
| `data.skipped` | recipients above the 5-broadcast cap |

### Error Response

```json
{ "status": "error", "message": "Device not paired" }
```

Common error causes: device not paired (re-do QR), WhatsApp Web session
expired (re-pair), attempting `image=` / `document=` with a path outside
`WHATSAPP_ATTACHMENT_ROOTS` (the file is rejected for security).

---

## Comprehensive trader alerts — the `scripts/alerts.py` layer

Hand-rolling f-strings for every event gets old fast. The helper module
ships pre-formatted templates for every event a strategy typically
broadcasts:

| Template | Function | Triggered when |
|----------|----------|----------------|
| Order placed | `fmt_order_placed(...)` | after `placeorder` succeeds |
| Order filled | `fmt_order_filled(...)` | after `poll_until_filled` returns |
| Stoploss triggered | `fmt_stoploss_triggered(...)` | SL order fills |
| Target hit | `fmt_target_hit(...)` | target order fills |
| Position closed | `fmt_position_closed(...)` | manual square-off or auto-square at session end |
| Scanner results | `fmt_scanner_results(...)` | end of a scan run |
| Daily P&L | `fmt_daily_pnl(...)` | end-of-day cron |
| Error | `fmt_error(...)` | any exception in a long-running strategy |

### One-call dispatcher

```python
from scripts.alerts import alert_order_lifecycle

alert_order_lifecycle(
    client,
    filled=dict(
        strategy="atm_straddle",
        symbol="NIFTY30JUN2626500CE",
        action="BUY",
        quantity=75,
        average_price=420.5,
        order_id="26063000000006",
        sl_price=294.0,
        target_price=630.0,
    ),
    via=("telegram", "whatsapp"),
)
```

`via` defaults to both channels — the helper skips whichever channel has no destination configured in `.env`.

### Multi-channel fan-out

`scripts.alerts.notify(...)` is the underlying primitive — every helper above goes through it. Use directly when you want full control over the message body:

```python
from scripts.alerts import notify

notify(
    client,
    f"NIFTY {ltp} now {pct_change:+.2f}% vs prev close",
    via=("telegram", "whatsapp"),
    whatsapp_to="919876543210",
)
```

### Sending a chart image

```python
from scripts.alerts import send_chart

# Generate the chart with scripts/plotting.py, save to attachments root
send_chart(client, "/srv/openalgo/db/attachments/intraday_nifty.png",
           caption="Intraday NIFTY 5m candles")
```

### Sending a PDF / CSV report

```python
from scripts.alerts import send_report

send_report(
    client,
    "/srv/openalgo/db/attachments/eod_pnl_2026-05-24.pdf",
    caption="EOD P&L summary",
    filename="EOD_2026-05-24.pdf",
)
```

---

## Failsafe behaviour

`scripts/alerts.notify` and all `fmt_*` helpers are designed so an
alert failure **never** crashes the strategy. The function catches
every exception, prints the diagnostic to stderr, and returns an
`AlertResult(telegram=..., whatsapp=...)` dataclass.

Inspect `result.ok` to branch on full success or fall back to a local
log:

```python
result = notify(client, msg, via=("telegram", "whatsapp"))
if not result.ok:
    print(f"[alert] partial failure: tg={result.telegram} wa={result.whatsapp}")
```

---

## Receiving WhatsApp commands

The paired device responds to slash-commands typed from your own phone
in the **"Message yourself"** chat. Random contacts who message your
number cannot drive the bot.

```
/help                   List all commands
/status                 Bot connection + paired status
/orderbook              Today's orders
/tradebook              Today's trades
/positions              Open positions
/holdings               Holdings
/funds                  Available cash / margin
/pnl                    Net P&L
/quote RELIANCE NSE     Last traded price
/closeall               Square off all positions
/mode                   Live or analyze mode
```

These commands are server-side — they run inside the OpenAlgo process and reply in the same chat. No client-side wiring required.

---

## Chained alert recipes

End-to-end pipelines that combine alerts with execution / scanning live in [common-workflows.md](common-workflows.md):

- `Order placed -> wait fill -> SL set -> alert all three events`
- `Daily P&L digest at 15:35 IST`
- `Scanner run -> top 10 by % change -> WhatsApp with attached CSV`
- `Error in long-running strategy -> stderr + alert + journal`
