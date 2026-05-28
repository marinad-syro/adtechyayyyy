# Deploy on Vercel (`vercel-demo` branch)

This branch drops **TribeV2** and uses **keyword matching on Vercel** (no PyTorch) plus optional **sentence-transformers** for local dev only. Fits Vercel’s 500 MB Lambda limit.

## Vercel project settings

| Setting | Value |
|---------|--------|
| **Root Directory** | *(leave empty — repo root; must contain `vercel.json`)* |
| **Framework Preset** | **Services** |
| **Build Command** | *(empty — Vercel installs from `requirements.txt` at repo root)* |
| **Output Directory** | *(empty)* |

All traffic is rewritten to `api/index.py`, which runs the FastAPI app and serves the frontend from `frontend/`.

## Environment variables

Set these in Vercel → Project → Settings → Environment Variables:

| Variable | Required | Purpose |
|----------|----------|---------|
| `XAI_API_KEY` | Recommended | Grok consumer chat + advertiser advisor |
| `XAI_MODEL` | Optional | Default `grok-3-fast` |
| `TAVILY_API_KEY` | Optional | Brand URL onboarding / market context |
| `DEMO_MODE` | Optional | Set to `embedding` (default on this branch) |

You do **not** need `HF_API_KEY` on this branch.

## Deploy steps

1. Push the branch:
   ```bash
   git push -u origin vercel-demo
   ```
2. [vercel.com/new](https://vercel.com/new) → Import your GitHub repo.
3. Select branch **`vercel-demo`**.
4. Add env vars above → **Deploy**.

CLI alternative:

```bash
npm i -g vercel
vercel --prod
```

## Notes

- **Vercel deploy** uses keyword relevance + hash-based emotional fit (no ML deps). Bundle stays under 500 MB.
- **Local dev** can optionally `pip install sentence-transformers numpy` for semantic ranking.
- **First request** on Vercel should be fast (no model download).
- **SQLite outcomes** live in `/tmp` on Vercel and reset on cold starts — fine for demos.
- **maxDuration** is set to 60s in `vercel.json` (Pro). Hobby plan caps at 10s — upgrade or trim `include_llm` if previews timeout.
- Full TribeV2 stack remains on the `brain-model` branch for local use.

## Local dev (same as before)

```bash
./setup.sh
./start.sh
# http://localhost:8000
```
