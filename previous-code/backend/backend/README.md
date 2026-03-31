# Ikshan Backend

FastAPI-powered backend for the Ikshan AI platform.

## Quick Start

```bash
# 1. Create virtual environment
python -m venv .venv

# 2. Activate (Windows)
.venv\Scripts\activate
# Or (macOS/Linux)
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment
cp .env.example .env
# Edit .env with your API keys

# 5. Run the server
uvicorn app.main:app --reload --port 8000
```

## API Docs

Once running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## Structure

```
backend/
├── app/
│   ├── main.py          # FastAPI entry point
│   ├── config.py        # Pydantic settings
│   ├── routers/         # API route handlers
│   ├── services/        # Business logic (OpenAI, Supabase, JusPay, Sheets)
│   ├── models/          # Pydantic request/response models
│   ├── middleware/       # Rate limiting, security
│   └── data/            # Static data (personas, extensions, GPTs)
├── requirements.txt
├── Dockerfile
└── .env.example
```
