# High-Impact News Alert for Discord (Myfxbook calendar)

Posts a red alert in your Discord channel about **30 minutes before every high-impact news release**, using the Myfxbook economic calendar.

Example alert:

> @Students 🚨 **HIGH-IMPACT NEWS in 30 min**
> **🔴 High-impact news at 7:00 PM IST**
> 🇺🇸 **United States Core Inflation Rate MoM** (USD)
>    Forecast: 0.3% | Previous: 0.2%
> 🕒 7:00 PM your time • in 30 minutes
> ⚠️ Expect sharp moves, wider spreads and slippage on USD pairs…

The time is shown in each student's **own** time zone automatically (Discord timestamps).

---

## Setup (about 10 minutes, free, no PC needed)

### 1. Create a Discord webhook
1. In your Discord server, open the channel for alerts (e.g. `#news-alerts`).
2. **Edit Channel → Integrations → Webhooks → New Webhook**.
3. Name it (e.g. "News Alert"), optionally add a logo, then **Copy Webhook URL**.
   Keep this URL private: anyone with it can post in that channel.

### 2. (Optional) Ping your students' role
1. Discord **User Settings → Advanced → Developer Mode** on.
2. **Server Settings → Roles**, right-click your students role → **Copy Role ID**.
3. Make sure the role is mentionable (Roles → your role → "Allow anyone to @mention this role").

### 3. Put the bot on GitHub
1. Create a free account at github.com and a **new private repository** (e.g. `news-alert`).
2. Upload all files from this folder, **including the hidden `.github` folder**
   (easiest: on the repo page click **Add file → Upload files** and drag the whole folder in).
3. In the repo: **Settings → Secrets and variables → Actions**
   - **Secrets → New repository secret**: name `DISCORD_WEBHOOK_URL`, value = the webhook URL.
   - **Variables → New repository variable** (all optional):
     - `ROLE_ID` = your students role ID
     - `COUNTRIES` = e.g. `United States,Euro Area,United Kingdom,Japan` (default: the major forex economies; `ALL` = every country Myfxbook marks High)
     - `ALERT_MINUTES` = how early to look ahead (default `35`, gives alerts ~30–35 min before)
4. **Settings → Actions → General → Workflow permissions** → choose **Read and write permissions** → Save.
5. Go to the **Actions** tab → enable workflows if asked → open **High-impact news alert** → **Run workflow** once to test.
   A green tick means it worked ("sent 0 alert(s)" is normal when no red news is due).

It then runs automatically every 5 minutes, 24/7.

---

## Good to know
- **Timing:** GitHub's scheduler can start runs a few minutes late, so alerts usually land 25–35 minutes before the release. If you need exact timing, run it on a PC or VPS instead:
  ```
  set DISCORD_WEBHOOK_URL=your_webhook_url      (Windows)
  export DISCORD_WEBHOOK_URL=your_webhook_url   (Mac/Linux)
  python news_alert.py --loop
  ```
  (Python 3.9+, no extra packages.) With `--loop` it checks every minute; set `ALERT_MINUTES=30`.
- **No duplicates:** sent alerts are remembered in `sent.json` (the bot updates it itself).
- **Test without posting:** `DRY_RUN=1 python news_alert.py` prints the message instead of sending.
- **GitHub pauses schedules after 60 days with no repo activity.** The bot's own commits normally count as activity; if it ever stops, open the Actions tab and re-enable the workflow.
- **Data source:** Myfxbook's public calendar RSS (`https://www.myfxbook.com/rss/forex-economic-calendar-events`). If Myfxbook changes the feed format, the bot will post nothing rather than wrong data; check the Actions log.
