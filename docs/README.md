# docs/

Working documentation for the AlphaDesk v2 build. Plan of record:
[`../V2_PLAN.md`](../V2_PLAN.md) — read its §0 (protocol + execution model)
before touching anything.

| Path | What it holds |
| --- | --- |
| `STATUS.md` | Live card ledger: what's done, in flight, next — updated by the orchestrator at every card completion and gate. Start here. |
| `SPECS/<card>.md` | Per card: what was built, the contract it exposes, decisions made along the way. Written by the card's agent, same branch as the code. |
| `TESTING/<card>.md` | Per card: how to run its tests, what they cover, how to verify by hand. |
| `design/` | D0 dashboard design bake-off: the 4–5 demos, `DECISION.md` (the locked design), `rejected/` (the record of what lost). |
| `ind_money_payloads.md` | C2 data-spike findings (created by C2; answers the five payload questions + go/no-go). |
| `screenshots/` | README screenshots. Kept out of the HF deploy snapshot — see STATUS.md deploy notes. |

**The bar for SPECS/TESTING:** an agent in a fresh session with zero
conversation history can pick up, debug, extend, and test the work from these
files plus the plan alone. If understanding the work requires a chat
transcript, the docs are incomplete and the card is not done.

Frontend-visible acceptance criteria are verified by looking at pixels —
computer-use or Stagehand (https://docs.stagehand.dev/v4/first-steps/introduction)
— never inferred from a green build. See V2_PLAN.md §0, "Visual verification".
