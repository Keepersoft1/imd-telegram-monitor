# IMD Telegram Monitor

Tracks:
- New IMD Explorer jobs: https://explorer.imd.fun/
- New Published Contracts: https://explorer.imd.fun/published?type=contracts

## Fast setup (Railway)

1. Open Telegram and create a bot with **@BotFather** using `/newbot`.
2. Copy the bot token.
3. Create a new Railway project and upload/deploy this folder (or push it to a private GitHub repo and connect Railway).
4. Add Railway variable:
   - `BOT_TOKEN` = token from BotFather
   - optional `CHECK_INTERVAL` = `60`
5. Deploy.
6. Open your new Telegram bot and send `/start`.
7. The bot saves the current IMD items as a baseline and only alerts on newly appearing jobs/contracts.

You do **not** need to manually find CHAT_ID: `/start` binds the bot to that Telegram chat.

Commands:
- `/start` — connect current chat
- `/chatid` — reconnect current chat
- `/status` — bot status

## Important

The monitor reads the public IMD Explorer HTML. If IMD changes the page structure, the parser may need an update.
On the first successful run it intentionally does not send the existing history, preventing notification spam.

For persistent deduplication across every redeploy, use a persistent Railway volume for `state.json`.
Without a persistent volume, a redeploy seeds a fresh baseline, so it still will not spam old entries, but it forgets the prior state.
Railway redeploy
Railway redeploy test
