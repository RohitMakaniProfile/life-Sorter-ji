# Ikshan — AI-Powered Business Solutions

A full-stack AI platform for business intelligence, chat, company discovery, and payments.

## Project Structure

```
life-sorter/
├── frontend/    # React + Vite SPA
├── backend/     # FastAPI Python API
└── docker-compose.yml
```

## Quick Start

### Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### Backend (FastAPI)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
cp .env.example .env         # Fill in API keys
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000/docs
```

### Docker (Both Services)

```bash
docker-compose up --build
```

## Tech Stack

| Layer     | Tech                        |
|-----------|-----------------------------|
| Frontend  | React 19, Vite, Lucide Icons |
| Backend   | FastAPI, Pydantic, structlog |
| AI        | OpenAI GPT-4o               |
| Database  | Supabase                    |
| Payments  | JusPay                      |
