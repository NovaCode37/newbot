# newbot — Advanced Telegram News Submission Bot

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-20.x-blue)
![Type](https://img.shields.io/badge/Type-Commercial%20Bot-orange)

An upgraded Telegram bot for community news submission with a full moderation pipeline, security layer, photo support, scheduled publishing, and inline editing. A complete rewrite of the original `predlozhkatg` bot.

## What's New vs v1

| Feature | v1 (predlozhkatg) | v2 (newbot) |
|---|---|---|
| Security layer | Manual checks | `SecurityManager` class |
| Rate limiting | None | 60s cooldown per user |
| Flood detection | None | ✅ Auto-block on >5 messages / 10s |
| Content filtering | None | ✅ Regex blacklist + pattern detection |
| User blocking | None | ✅ Persistent blocked users set |
| Token validation | Existence check only | ✅ Regex format validation |
| Photo support | ❌ | ✅ Optional photo attachment |
| Scheduled publishing | ❌ | ✅ 1h / 3h / custom delay |
| Inline editing | ❌ | ✅ Moderator can edit before publish |
| Spam marking | ❌ | ✅ Dedicated SPAM button |
| Conversation steps | 2 (title → text) | 3 (title → text → photo) |
| Logging | Console only | ✅ File + console with timestamps |
| Config via env | Partial | ✅ Fully configurable via `.env` |

## Moderation Panel

Each submission arrives in the moderation group with a full inline keyboard:

```
[ Опубликовать ]  [ Отклонить ]
[ Редактировать ] [ СПАМ      ]
[ 1ч ]  [ 3ч ]  [ Свое время ]
```

- **Publish** — posts immediately to the channel, notifies author
- **Reject** — notifies author with rejection message
- **Edit** — moderator edits the post inline before publishing
- **SPAM** — marks as spam, blocks the submitting user
- **Delay** — schedules publication at 1h / 3h / custom time

## Security Architecture

```
Incoming user message
        │
        ├─ is_user_blocked()        → hard block, no processing
        ├─ check_flood()            → >5 msgs in 10s → auto-block
        ├─ check_rate_limit()       → 60s cooldown between submissions
        ├─ check_content()
        │       ├─ regex blacklist (BLACKLISTED_WORDS from env)
        │       ├─ repeated character pattern (spam detection)
        │       ├─ max length (MAX_NEWS_LENGTH)
        │       └─ max URLs per post (MAX_URLS)
        │
        └─ Passed → enter ConversationHandler
```

## Features

- **3-step submission flow** — title → body text → optional photo
- **Photo support** — attach image to news post, or skip
- **Configurable limits** — all thresholds via `.env`, no hardcoding
- **Structured logging** — `bot.log` file + console, with timestamps and levels
- **Admin whitelist** — `ADMIN_USER_IDS` set from environment
- **Stale submission guard** — processed submissions removed from memory, replay-safe

## Tech Stack

- `python-telegram-bot` 20.x (fully async)
- `python-dotenv`
- Standard library: `re`, `asyncio`, `datetime`, `typing`

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in values
python bot.py
```

## Environment Variables

```bash
BOT_TOKEN=                    # Telegram bot token (validated on startup)
MODERATION_GROUP_ID=          # Group ID for moderation queue
CHANNEL_ID=                   # Target channel ID for published posts
ADMIN_USER_IDS=               # Comma-separated admin Telegram IDs
MAX_NEWS_LENGTH=4000          # Max body text length
MAX_TITLE_LENGTH=200          # Max title length
MAX_URLS=3                    # Max URLs allowed per submission
BLACKLISTED_WORDS=            # Comma-separated banned word patterns (regex)
```

## Project Structure

```
newbot/
├── bot.py              ← full bot logic + SecurityManager class
├── requirements.txt
├── .env.example
└── .gitignore          ← .env excluded from version control
```
