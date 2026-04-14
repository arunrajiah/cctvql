# Notifications

cctvQL can send alerts to multiple channels when an alert rule fires. All channels are configured under the `notifications:` key in `config/config.yaml`.

You can enable any combination of channels — they all fire concurrently for every matching event.

---

## Quick Setup

Add a `notifications:` section to your `config/config.yaml`:

```yaml
notifications:
  webhooks:
    - url: https://example.com/hook

  telegram:
    bot_token: "123456:ABC-DEF..."
    chat_id: "-1001234567890"

  slack:
    webhook_url: "https://hooks.slack.com/services/T.../B.../..."

  ntfy:
    topic: my-cctvql-alerts
    server: https://ntfy.sh   # optional, defaults to ntfy.sh

  email:
    smtp_host: smtp.gmail.com
    smtp_port: 587
    username: you@gmail.com
    password: ""              # use CCTVQL_SMTP_PASSWORD env var instead
    from_addr: you@gmail.com
    to_addrs:
      - recipient@example.com
    use_tls: true
```

---

## Channels

### Webhook

Posts a JSON payload via HTTP `POST` to any URL. Works with Home Assistant, Zapier, Make (Integromat), ntfy self-hosted, and any custom endpoint.

```yaml
notifications:
  webhooks:
    - url: https://example.com/alerts/hook
    - url: https://another-system.local/webhook   # multiple webhooks supported
```

**Payload sent:**
```json
{
  "rule_id": "rule_abc123",
  "rule_name": "Night Person Alert",
  "camera_name": "Front Door",
  "label": "person",
  "confidence": 0.94,
  "zones": ["porch"],
  "snapshot_url": "http://192.168.1.100:5000/api/events/xyz/snapshot.jpg",
  "clip_url": "http://192.168.1.100:5000/api/events/xyz/clip.mp4",
  "ts": "2026-04-14T22:47:03"
}
```

**Home Assistant example** — use a webhook automation to trigger an HA script:
```yaml
notifications:
  webhooks:
    - url: http://homeassistant.local:8123/api/webhook/cctvql_alert
```

---

### Telegram

Sends a message to a Telegram chat or group.

**Setup:**
1. Create a bot via [@BotFather](https://t.me/BotFather) — it gives you a `bot_token`
2. Start a chat with the bot (or add it to a group)
3. Get the `chat_id`:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   The `chat.id` field in the first update is your chat ID. Group IDs start with `-100`.

```yaml
notifications:
  telegram:
    bot_token: "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
    chat_id: "-1001234567890"
```

**Example message sent:**
```
🚨 cctvQL Alert — Night Person Alert
📷 Camera: Front Door
🏷️ Detected: person (94%)
📍 Zone: porch
🕙 2026-04-14 22:47:03

🖼 http://192.168.1.100:5000/api/events/xyz/snapshot.jpg
```

---

### Slack

Posts to a Slack channel via an Incoming Webhook.

**Setup:**
1. Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From Scratch
2. Enable **Incoming Webhooks** under Features
3. Click **Add New Webhook to Workspace** and pick a channel
4. Copy the webhook URL

```yaml
notifications:
  slack:
    webhook_url: "https://hooks.slack.com/services/YOUR_TEAM/YOUR_CHANNEL/YOUR_TOKEN"
```

**Example message sent:**

> **🚨 cctvQL Alert — Night Person Alert**  
> Camera: `Front Door` | Label: `person (94%)` | Zone: `porch`  
> [View snapshot](http://192.168.1.100:5000/api/events/xyz/snapshot.jpg)

---

### ntfy

[ntfy](https://ntfy.sh) is a simple push notification service. Free public server at `ntfy.sh`, or self-host for full privacy.

```yaml
notifications:
  ntfy:
    topic: my-cctvql-alerts         # choose any unique topic name
    server: https://ntfy.sh         # or your self-hosted URL
```

**Receiving on mobile:**
1. Install the ntfy app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347))
2. Subscribe to your topic: `ntfy.sh/my-cctvql-alerts`

> ⚠️ **Privacy note:** on the public ntfy.sh server, topic names are effectively public URLs. Use a long random topic name (e.g., `cctvql-a3f92b1e`) or run your own ntfy server.

**Self-hosting ntfy with Docker:**
```bash
docker run -d --name ntfy -p 8080:80 binwiederhier/ntfy serve
```
Then set:
```yaml
notifications:
  ntfy:
    topic: my-alerts
    server: http://localhost:8080
```

---

### Email

Sends alert emails via SMTP with TLS.

```yaml
notifications:
  email:
    smtp_host: smtp.gmail.com
    smtp_port: 587
    username: your-account@gmail.com
    password: ""                  # see env var below
    from_addr: your-account@gmail.com
    to_addrs:
      - you@example.com
      - partner@example.com
    use_tls: true
```

> **Gmail tip:** use an [App Password](https://myaccount.google.com/apppasswords) instead of your Google account password. Enable 2FA first.

**Setting the password via environment variable (recommended):**

```bash
export CCTVQL_SMTP_PASSWORD="your-app-password"
```

Or in `docker-compose.yml`:
```yaml
environment:
  CCTVQL_SMTP_PASSWORD: "your-app-password"
```

**Other SMTP providers:**

| Provider | `smtp_host` | `smtp_port` |
|----------|------------|-------------|
| Gmail | `smtp.gmail.com` | `587` |
| Outlook / Hotmail | `smtp-mail.outlook.com` | `587` |
| Yahoo | `smtp.mail.yahoo.com` | `587` |
| Custom / self-hosted | your server | `587` or `465` |

---

## Testing Notifications

Use the CLI to send a test notification to all registered channels:

```bash
cctvql notify-test --config config/config.yaml
```

Or fire a test webhook manually:
```bash
curl -X POST https://example.com/hook \
  -H "Content-Type: application/json" \
  -d '{"test": true, "source": "cctvql"}'
```

---

## Alert Rules

Notifications are triggered by **alert rules**. Create rules via the REST API:

```bash
curl -X POST http://localhost:8000/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Night Person Alert",
    "camera_name": "Front Door",
    "label": "person",
    "time_start": "22:00",
    "time_end": "06:00"
  }'
```

Or using natural language through the query interface:
```
> Notify me when a person is detected on the front door camera after 10pm
```

See [api.md](api.md#alert-rules) for the full alert rules API reference.

---

## Architecture

```
Alert Engine
    │
    ├── matches rule? ──► AlertRule.matches(event)
    │
    └── NotifierRegistry.broadcast(notification)
            │
            ├── WebhookNotifier  (HTTP POST)
            ├── TelegramNotifier (Telegram Bot API)
            ├── SlackNotifier    (Slack Incoming Webhook)
            ├── NtfyNotifier     (ntfy HTTP API)
            └── EmailNotifier    (aiosmtplib)
```

All notifiers run concurrently via `asyncio.gather`. A failure in one channel does not affect the others.
