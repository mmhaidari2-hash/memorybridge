# Local laptop bring-up (free)

## Fastest way

```bash
git clone https://github.com/mmhaidari2-hash/memorybridge.git
cd memorybridge
git checkout cursor/v04-commercial-foundation-9c9c
chmod +x scripts/dev_up.sh
./scripts/dev_up.sh
```

Then open: **http://localhost:8000**

What the script does:
1. Creates `.env` with SQLite (no Postgres needed)
2. Installs Python deps
3. Runs migrations
4. Builds the website
5. Starts the API + site together

Stop with `Ctrl+C`.

## What you can test

- Landing page + pricing modal
- Free signup → get API key
- `/docs` Swagger if enabled (FastAPI default at `/docs`)
- Admin plan assign with `ADMIN_API_KEY` from `.env`

## Reset local DB

```bash
rm -f memorybridge.db
./scripts/dev_up.sh
```

## Requirements on your laptop

- Python 3.11+
- Node.js 20+ (for website build)
- No paid cloud account needed
