# TylerBot - Habit Tracker (Telegram)

MVP features:
- Add a new habit (`/add`)
- Mark habit done for today (`/done`)
- Weekly visual matrix (`/week`) with green/red squares

## Run

1. Create bot in @BotFather and get token.
2. Prepare env:

```bash
cp .env.example .env
# put BOT_TOKEN=...
```

3. Install and start:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Notes
- Uses SQLite (`database.sqlite3`) in project root.
- One habit can be marked once per day.
