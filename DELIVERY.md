# Delivery Guide (M6)

## Quick Start

### Backend
```bash
source demo/bin/activate
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

---

## Configuration

Backend `.env` (already in repo root):
- `API_KEY` (optional): if set, requests must include `x-api-key` or `Authorization: Bearer`.
- `DATABASE_URL`: MySQL connection string.
- `DB_STRICT=false`: if MySQL is unavailable, fallback to JSON mock data.

Frontend `.env` (optional):
- `VITE_API_BASE_URL` (default `http://localhost:8000`)
- `VITE_API_KEY`

---

## MySQL Setup & Seeding

Create database if needed:
```sql
CREATE DATABASE inventory_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Initialize schema:
```bash
source demo/bin/activate
python scripts/init_mysql.py
```

Generate mock data:
```bash
source demo/bin/activate
python scripts/generate_mock_data.py --items 5000 --vendors 20
```

---

## Health & Monitoring

Health checks:
```bash
API_KEY=your_key scripts/health_check_mac.sh http://localhost:8000
```

Metrics:
- `GET /metrics` (Prometheus-like text output)

Performance smoke test:
```bash
python scripts/perf_smoke.py --base-url http://localhost:8000 --concurrency 50 --total 200
```

---

## Manual E2E Checklist

1. Start backend and frontend.
2. Load dashboard and confirm stats populate.
3. Run chat query (e.g. "Show stockout risks").
4. Confirm risk table updates for Stockout Sentinel.
5. Check `/health` and `/metrics`.
