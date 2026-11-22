# JobPilot Setup Guide

## 1. Prerequisites

- Python 3.11+
- Playwright Chromium: `playwright install chromium`
- An Anthropic API key
- (Optional) A Telegram bot or SMTP credentials for daily digests

---

## 2. Install

```bash
git clone <repo>
cd JobPilot
pip install -e ".[dev]"
```

---

## 3. Configure

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

Edit `profile.yaml` with your personal details, target countries, and fixed answers.
Edit `config.yaml` to adjust scoring thresholds and LLM models.

---

## 4. Database

```bash
alembic upgrade head
```

---

## 5. Telegram Notifications (recommended)

1. Open Telegram, start a chat with [@BotFather](https://t.me/BotFather) and run `/newbot`.
2. Copy the bot token into `TELEGRAM_BOT_TOKEN` in `.env`.
3. Send any message to your new bot, then visit:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
4. Copy the `chat.id` value from the response into `TELEGRAM_CHAT_ID` in `.env`.
5. Test: `jobpilot daily --dry-run` — you should see the digest text printed but not sent.

---

## 6. SMTP / Email Notifications (fallback)

If `TELEGRAM_BOT_TOKEN` is empty, the daily digest falls back to SMTP.

Fill in `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, and `SMTP_TO` in `.env`.

**Gmail**: generate an [App Password](https://myaccount.google.com/apppasswords), set port 587.

---

## 7. Schedule the Daily Run

### macOS/Linux — cron

```bash
crontab -e
```

Add (runs at 07:00 each day, logging to `~/.jobpilot/daily.log`):

```cron
0 7 * * * cd /path/to/JobPilot && /path/to/venv/bin/jobpilot daily >> ~/.jobpilot/daily.log 2>&1
```

Create the log directory:

```bash
mkdir -p ~/.jobpilot
```

### macOS — launchd (more reliable than cron)

Create `~/Library/LaunchAgents/com.jobpilot.daily.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jobpilot.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/venv/bin/jobpilot</string>
        <string>daily</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/JobPilot</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/YOUR_USER/.jobpilot/daily.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USER/.jobpilot/daily.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.jobpilot.daily.plist
```

### Windows — Task Scheduler

```powershell
$action = New-ScheduledTaskAction `
    -Execute "C:\path\to\venv\Scripts\jobpilot.exe" `
    -Argument "daily" `
    -WorkingDirectory "C:\path\to\JobPilot"

$trigger = New-ScheduledTaskTrigger -Daily -At "07:00"

Register-ScheduledTask -TaskName "JobPilot Daily" `
    -Action $action -Trigger $trigger -RunLevel Highest
```

### Remote Server (systemd timer)

`/etc/systemd/system/jobpilot-daily.service`:

```ini
[Unit]
Description=JobPilot daily run

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/JobPilot
ExecStart=/home/ubuntu/venv/bin/jobpilot daily
EnvironmentFile=/home/ubuntu/JobPilot/.env
```

`/etc/systemd/system/jobpilot-daily.timer`:

```ini
[Unit]
Description=Run JobPilot daily at 07:00 UTC

[Timer]
OnCalendar=*-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jobpilot-daily.timer
sudo systemctl list-timers jobpilot-daily.timer
```

---

## 8. Manual Run

```bash
# Full run with notifications
jobpilot daily

# Preview only — no DB writes, no messages sent
jobpilot daily --dry-run

# Force a catch-up run (skips the 20-hour cooldown check)
jobpilot catchup
```

---

## 9. Checking Logs

```bash
# Last 10 runs
jobpilot stats

# Tail the log (if using cron/launchd)
tail -f ~/.jobpilot/daily.log
```
