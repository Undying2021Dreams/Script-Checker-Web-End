# Web-End

Web app for authoring handwritten exam papers, extracting students' answers
from a photo or scan of the completed page, and marking them with an LLM
under a teacher's review.

## How it works

A teacher writes a question paper in a rich-text editor, marking out
**answer boxes** (where the student writes) and **model answers** (the
answer key, never printed). Finalizing renders the paper to PDF with ArUco
corner markers and a per-box QR code baked in.

A completed page is photographed or scanned and uploaded. The extractor
locates the markers, corrects the page's perspective, and crops out each
answer box, verifying each crop against its printed QR code.

Each crop is then paired with the model answer it belongs to — by document
order, since answer boxes and model answers have no explicit link — and
sent to an LLM along with the question and the marks available. The teacher
reviews every mark, can override any of them, and releases them to the
student.

Marks the system can't stand behind are never invented. No model answer, no
extracted crop, an unreadable scan, an unparseable reply, or a score outside
the valid range are all flagged for manual review, which is distinct from a
score of zero.

## Stack

- **Backend** — FastAPI, PostgreSQL + Alembic, Playwright (PDF rendering),
  OpenCV (extraction), Microsoft Entra ID auth
- **Frontend** — React + TypeScript + Vite, Tailwind + shadcn/ui, TanStack
  Query, Tiptap editor, MSAL

## Running it locally

### 1. Database and Redis

```bash
docker compose up -d
```

Postgres is mapped to **5434** rather than 5432 to avoid colliding with an
existing local Postgres install.

### 2. Register a Microsoft Entra ID app

Auth is Microsoft sign-in, so you need your own app registration:

1. At [entra.microsoft.com](https://entra.microsoft.com), search
   **App registrations** → **New registration**.
2. Supported account types: **Any Entra ID Tenant + Personal Microsoft
   accounts**. (This is what lets a university-issued account sign in
   without that university's IT having to approve anything.)
3. **Authentication → Add a platform → Single-page application**, redirect
   URI `http://localhost:5173`.
4. **Expose an API** → accept the default Application ID URI → **Add a
   scope** named `access_as_user`.
5. **API permissions → Add a permission → My APIs** → this same app →
   `access_as_user`.

Note the Application (client) ID.

### 3. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env      # then fill in AZURE_CLIENT_ID and TEACHER_EMAILS
alembic upgrade head
uvicorn main:app --reload --port 8000
```

`TEACHER_EMAILS` is a comma-separated list; those accounts get the teacher
role on first sign-in, everyone else becomes a student.

### 4. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # fill in the same client id
npm run dev
```

Open http://localhost:5173.

### Tests

```bash
cd backend && python3 -m pytest
```

They run against a `webend_test` database and use a fake LLM provider, so
no API key or model is needed.

## AI providers

Grading and the authoring helpers work with Gemini, OpenAI, Claude, or a
self-hosted open-source model exposing an OpenAI-compatible endpoint.
Configure whichever you want in `backend/.env`.

`kaggle_self_hosted_llm.py` runs the self-hosted option as a Kaggle
notebook: a vision-language model behind an OpenAI-compatible
`/chat/completions` endpoint, tunnelled out with ngrok. Put the printed
URL in `SELF_HOSTED_LLM_URL`. `MODEL_ID` near the top is the only thing
to change to swap models, and the comment there says what fits on which
Kaggle accelerator.

Set `NGROK_DOMAIN` in the notebook to a reserved ngrok domain (the free
tier includes one permanent domain, under Domains in the ngrok
dashboard). The tunnel URL is then fixed, so `SELF_HOSTED_LLM_URL`
survives every restart; left blank, ngrok assigns a random URL that has
to be copied across again each time.

Kaggle sessions still expire, so a notebook is fine for development but
not something a deployed instance can depend on staying up.

Be aware that hosted-provider costs are billed by that provider and are
outside any cloud spending cap you may have set. If you deploy this
somewhere reachable, prefer the self-hosted provider and set spend limits
on any hosted keys.

## Status

Working: courses and enrollment, question authoring, PDF export, answer
extraction, LLM grading with teacher override and release, submission
review.

Not yet built: the course gradebook view, the student-facing view of
released marks, and deployment configuration.
