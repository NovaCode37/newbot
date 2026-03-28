# predlozhkatg — Telegram News Submission Bot

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-20.x-blue)
![Type](https://img.shields.io/badge/Type-Commercial%20Bot-orange)

A Telegram bot for community-driven news submission with a full moderation pipeline. Users submit news proposals, moderators approve or reject them via inline buttons, and accepted posts are published directly to a Telegram channel.

## How It Works

```
User                    Moderation Group              Channel
 │                            │                          │
 ├─ /start                    │                          │
 ├─ [Suggest news]            │                          │
 ├─ Enter title               │                          │
 ├─ Enter body text           │                          │
 │                            │                          │
 └─ "Sent for moderation" ───►│                          │
                              │  [Publish] [Reject]      │
                              │                          │
                    Publish ──┼─────────────────────────►│ Post published
                    Reject ───┤                          │
                              └─► User notified          │
```

## Features

- **Multi-step ConversationHandler** — guided title → body submission flow
- **Inline moderation** — Publish / Reject buttons in the moderation group chat
- **User notifications** — author is notified on publish or rejection
- **Deduplication** — each submission gets a `user_id_timestamp` unique key, prevents double-processing
- **Graceful error handling** — failed user notifications are logged, bot continues running
- **Cancel command** — `/cancel` exits submission flow at any step, clears user state

## Security Practices

- **Token from environment** — `BOT_TOKEN` loaded via `python-dotenv`, never hardcoded; bot exits immediately if token is missing
- **Channel/group IDs from environment** — `MODERATION_GROUP_ID` and `CHANNEL_ID` via `.env`
- **No user data persistence** — `context.user_data` cleared after each completed or cancelled conversation
- **Callback pattern filtering** — `button_callback` only triggers on `publish_*` / `reject_*` patterns, preventing arbitrary callback injection
- **Stale submission guard** — submissions deleted from memory after processing; replayed callbacks return "already handled"

## Tech Stack

- `python-telegram-bot` 20.x (async)
- `python-dotenv` for secrets management

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in values
python bot.py
```

## Environment Variables

```bash
BOT_TOKEN=your_bot_token_here
MODERATION_GROUP_ID=-100xxxxxxxxxx
CHANNEL_ID=-100xxxxxxxxxx
```

## Project Structure

```
predlozhkatg/
├── bot.py           ← full bot logic (handlers, moderation flow)
├── requirements.txt
├── .env.example
└── .gitignore       ← .env excluded from version control
```
