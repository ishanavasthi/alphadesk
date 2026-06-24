# AlphaDesk Frontend

Next.js 15 (App Router) · TypeScript · Tailwind CSS · shadcn/ui (new-york). A
dark, Bloomberg-terminal-lite UI for the AlphaDesk research desk.

## Run

```bash
cd frontend
npm install
cp .env.local.example .env.local   # point NEXT_PUBLIC_API_URL at the backend
npm run dev                        # http://localhost:3000
```

The backend (FastAPI, port 8000) must be running — it already allows the
`http://localhost:3000` origin via CORS.

## Structure

- `app/page.tsx` — Home: command-line query bar; swaps to the dashboard on submit.
- `components/ResultsDashboard.tsx` — streams `/analyze` over SSE; drives the
  5-stage pipeline rail and renders recommendation cards.
- `components/AgentStepCard.tsx` — one pipeline stage (queued → running → done).
- `components/RecommendationCard.tsx` — bull/bear thesis, target, confidence,
  action + risk badges.
- `components/ApprovalModal.tsx` — human-in-the-loop gate; calls `POST /approve`.
- `lib/api.ts` — typed SSE client + approve call.
