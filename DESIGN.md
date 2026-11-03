# Design: LLM spend agent

Author: Ananmay Narain. Status: draft for review. Requirements: `project-brief-llm-spend-agent.md`.

## 1. Problem and users

**Users.** Executives who own AI budgets: CEO, CFO, FinOps lead, engineering leaders. The v1 beta serves 5–20 organisations (tenants), each with several such users. They ask questions in plain English through an LLM host they already use (Claude, Cursor).

**What they ask.**
- "What did we spend on LLMs this month, by provider and model?"
- "Who spent the most last week?"
- "How many tokens did each model consume, and how much of it was cached?"
- "How much did web search cost us this month?"

**Why not the provider dashboards.** Spend is split across consoles (Anthropic, OpenAI) that use different terms (workspaces vs projects), different token categories and different exports. Answering one cross-provider question today means logging into each console, downloading CSVs and reconciling them by hand. The dashboards also stop at the API key or project. They do not answer "which person or team", which chargeback needs.

**What this is.** An MCP server that pulls usage and cost from each provider's Admin API, normalises it into one shape, and lets the user's own LLM answer questions about it with numbers the server computes, always labelled with the date range and how fresh the data is.

## 2. Requirements and non-goals

**v1 scope:** Anthropic and OpenAI, connected with an Admin API key for each. Starts as a local server; v1 is complete when it is hosted with OAuth and rolled out as a beta to 5–20 tenants.

Requirements (each must be true for v1 to ship):

1. **Spend.** Answer spend questions grouped by provider, model, API key, key owner, workspace/project, or cost type (tokens, web search, other tools), over any date range.
   *Test:* "Show me all models ordered by spend this week" returns every model with spend in that range, sorted, with totals.
2. **Usage.** Answer usage questions using every metric the APIs export: requests, input tokens, output tokens, cache-write tokens, cache-read tokens, and tool calls such as web search. See §4.
   *Test:* "Show me all models ordered by tokens consumed" matches the provider usage APIs exactly.
3. **Spend and usage together** in one answer.
   *Test:* "Models by cost with input and output tokens this month" returns both in one table.
4. **Attribution to people.** Spend and usage per API key, resolved to the key's owner (name or email) from the Admin API.
   *Test:* "Who spent the most this month?" returns a named person, not only a key ID.
5. **Correctness.**
   - Totals the server reports as *provider-reported cost* match the provider cost APIs to the cent for the same range.
   - Usage totals match the usage APIs exactly.
   - Per-key and per-person cost is *estimated at list price* and labelled as such.
6. **Transparency.** Every answer includes the resolved date range, the time zone, `data_as_of` for each provider, and, for estimated costs, the version date of the price list used.
7. **Security.**
   - Admin keys are never returned by a tool, written to logs or committed to git.
   - Every tool only reads data.
   - The model never writes SQL; the server builds every query.
   - Text from provider data is treated as data, never as instructions.
   - Locally, only the person who configured the keys can query. Once hosted, only users signed in through OAuth can query.
   - Admin keys are entered only through an onboarding web page and stored encrypted. They are never accepted as tool arguments or through the conversation.
8. **Guardrails.** No tool returns more than `top_n` rows (default 10, max 100). The rest is rolled into an "other" row, so a request that would return millions of rows still returns a small, correct summary.
9. **Context for the model.**
   - Tool descriptions say when to use each tool and how to chain them.
   - All tool descriptions together stay under ~1,500 tokens.
   - The server instructions describe the data model in a few lines.
10. **Multiple tenants (hosted).** Serve 5–20 organisations from one deployment.
    - Each tenant's data is stored separately and can only be read by that tenant's users.
    - A user's tenant comes from their OAuth identity, never from a tool argument.
    - Several users per tenant are allowed. An admin connects the provider keys once.
    - Two people connecting the same provider organisation join the same tenant instead of creating a duplicate.
    *Test:* a user from tenant A cannot get any of tenant B's data through any tool or argument.

**Non-goals for v1** (decided deliberately, not forgotten):

1. **Forecasting, anomaly detection, budgets and alerts.** v1 reports what happened. Prediction is a different product with different accuracy needs.
2. **Optimisation advice and live pricing or benchmark data.** No recommendations, no live price fetching. Estimates use a static list-price table kept in the repo (§4).
3. **Spend outside the Admin APIs:**
   - **Cloud marketplace usage** (Claude on Bedrock or Vertex, OpenAI on Azure) is billed through the cloud provider.
   - **Seat subscriptions** (e.g. a $20/month Pro plan, Team or Enterprise seats) are fixed costs that usage analysis can't change.
   - **Invoices:** no negotiated discounts, credits, commitments or tax. v1 means *list price as reported by the APIs*, and answers say so.
4. **Write actions.** No creating keys, changing limits or editing anything in provider accounts.
5. **Our own host (chat app).** Users bring their own MCP host (Claude, Cursor). A branded host is Phase 2.
6. **Scale beyond ~20 tenants, roles and high availability.** v1 runs one instance for a small beta. Viewer/admin roles, per-department access and more than one instance are Phase 2.
7. **Currencies other than USD.**

## 3. Architecture

Ingestion (the write side) is separate from serving (the read side). Tools never call provider APIs. They only read the local store.

```
Anthropic Admin API ─► Anthropic adapter ─┐
                                          ├─► Normaliser ─► Sync ──write───► Store (DuckDB file per tenant)
OpenAI Admin API ────► OpenAI adapter ────┘                                     │
                                                                                ▼
MCP host (Claude/Cursor) ◄─MCP─► MCP server (tools) ─► Query layer ─────────── reads
                                                          ▲
                                         Price list (pricing.yaml, versioned)
```

| Component | Responsibility | Tested without network or model? |
|---|---|---|
| **Adapters** | Call the provider endpoints; handle paging, retries and rate limits; return raw JSON | Yes, with recorded responses |
| **Normaliser** | Turn raw JSON into normalised rows; compute estimated cost from tokens × list price | Yes, pure functions |
| **Sync** | Fetch new data incrementally with a 3-day look-back; replace the re-fetched days in one transaction; record `data_as_of` per provider. Runs per tenant. | Yes, with fake adapters and a temporary database |
| **Store** | One DuckDB file per tenant with the facts, key/user lookup tables and sync state (§4) | Yes |
| **Tenant registry** | Tenants, their users (by OAuth identity), their provider organisation IDs, and references to their encrypted keys | Yes |
| **Onboarding page** | Small web page behind OAuth where a tenant admin connects provider keys. Keys are checked, then stored as encrypted secrets. | Yes, with fake key checks |
| **Query layer** | Parameterised SQL for aggregates; top-N plus "other"; resolves time periods (§4) | Yes, against a fixture database |
| **MCP server** | Tool definitions and descriptions; returns query results with metadata | Yes, with MCP Inspector, no model needed |

**When sync runs:**
- **Local:** a backfill CLI (`sync --backfill 90d`), a sync at server start, and a sync before answering if data is older than 1 hour. That sync gives up after a time limit; if it does, the answer uses the stored data and says it is stale.
- **Hosted:** the same `sync()` function runs on an hourly timer inside the server, looping over tenants. Tenants are spread across the hour so they don't all sync at once. A new tenant's 90-day backfill runs in the background, and `data_status` shows its progress.

**Deployment path:**
- **Local:** stdio transport; one implicit tenant; keys in environment variables or a `.env` file that git ignores.
- **Hosted beta:** a single container, pinned to one instance, using the Streamable HTTP transport behind OAuth.
  - Tenant DuckDB files and raw Parquet sit on one volume.
  - Keys are encrypted secrets, one set per tenant.
  - Sizing: 2 vCPU, 4 GB RAM and a 20 GB volume cover the worst case in §4.

**Tenant isolation:**
- On every tool call, the server looks up the tenant from the signed-in OAuth identity and opens only that tenant's file.
- Tools have no tenant argument, so the model cannot ask for another tenant's data.

## 4. Data model

One normalised shape so a single query answers cross-provider questions. Provider differences are handled once, in the normaliser, instead of in every query. All amounts are in USD and all timestamps in UTC, in daily buckets.

**`usage_facts`.** One row per day × provider × API key × model × service tier. This is where per-person attribution lives.

| Column | Notes |
|---|---|
| `date`, `provider`, `model`, `service_tier` (standard / batch / priority) | |
| `api_key_id`, `workspace_or_project_id` | Anthropic workspace ≈ OpenAI project |
| `requests` | Number of model requests |
| `input_tokens` | Uncached input |
| `cache_write_tokens` | Anthropic cache creation (5-minute and 1-hour kept separate in raw data). Zero for OpenAI. |
| `cache_read_tokens` | Anthropic cache reads; OpenAI cached input |
| `output_tokens` | |
| `web_search_requests`, `other_tool_calls` | Server-side tool use where the API reports it |
| `est_cost_usd` | Tokens and tool calls × list price from `pricing.yaml` |
| `price_list_version` | Version date of the price list used |

**`cost_facts`.** Cost as each provider reports it. These are the authoritative totals.

| Column | Notes |
|---|---|
| `date`, `provider`, `workspace_or_project_id`, `model` (when given) | |
| `cost_type` | tokens / web_search / code_execution / other; taken from Anthropic's cost type or OpenAI's line item |
| `cost_usd` | |

**Lookup and state tables:**
- `api_keys`: key ID → name, owner user ID, workspace/project
- `users`: user ID → name, email
- `sync_state`: per provider, the last synced date, `data_as_of`, and the last error

**Storage layout:**
- `data/tenants/<tenant_id>.duckdb`: one file per tenant, holding the tables above plus a `schema_version` table. Migrations bring every tenant file up to date at startup.
- `data/raw/<tenant_id>/<provider>/<date>.parquet`: raw API responses, compressed and kept outside the database. Kept for 90 days, only for reprocessing after a normaliser fix.
- **No double counting on re-sync:** in one transaction, delete the tenant's rows for that provider and the re-fetched days, then insert the fresh rows. This avoids a primary-key index over millions of rows.

**Volume (worst case):**
- A large tenant has ~1,000 active keys per provider × 5 models × 2 service tiers, which is ~20,000 usage rows a day, or ~9M rows a year including cost rows.
- 20 such tenants is ~180M rows a year, about 5–7 GB compressed.
- A typical beta tenant has ~130k rows a year.
- Each query reads only one tenant's file, so queries take milliseconds.
- Daily buckets are kept on purpose: hourly buckets would multiply the row count by 24.

**Why two cost figures.** As far as we know, both providers' cost endpoints break down only to workspace/project and line item, not to API key. Per-person cost therefore has to be *estimated* from tokens × list price. Reported cost stays the source of truth for totals. A daily check compares estimated and reported cost per workspace/project and flags a gap above 2%.

**Lost in normalisation:**
- Provider-specific fields such as audio and image tokens, context-window tier and data-residency tier are kept in a raw JSON column, not as columns.
- Cache-write 5-minute and 1-hour tokens are merged into one column.
- Long-context and residency price multipliers may make estimates slightly off. The reconciliation check above surfaces this.

**Time rules:**
- **Storage:** UTC, daily buckets, because both providers report cost per UTC day.
- **Ranges:** the start date is included and the end date is included as the user says it. Internally a range is stored as [start, end + 1 day).
- **Named periods are resolved by the server, not the model.** Tools take `period` values:
  - `today`
  - `yesterday`
  - `this_week`: Monday to now
  - `last_week`
  - `this_month`
  - `last_month`
  - `last_7_days`, `last_30_days`: including today
  - `year_to_date`

  Tools also accept explicit `start`/`end` dates.
- **Partial data:** today and yesterday are marked *provisional*, because providers revise recent buckets. Each sync re-fetches the last 3 days.
- **Every result** includes the resolved `start`, `end`, `timezone: UTC`, `data_as_of` per provider, and `provisional: true/false`.

## 5. Interfaces

Three tools. Fewer, more general tools keep the token cost of the tool list low and leave the model fewer wrong choices.

| Tool | Inputs | Output | Example question |
|---|---|---|---|
| `query_spend_usage` | `metrics` (cost, est_cost, tokens by type, requests, web_search…), `group_by` (provider, model, key_owner, api_key, workspace, cost_type, day, week, month), `period` or `start`/`end`, `filters`, `top_n` | Small table plus totals plus metadata (range, `data_as_of`, provisional, price list version) | "Which models cost the most this month, with input/output tokens?" |
| `list_dimensions` | `dimension` (models, key_owners, workspaces, providers) | The values that exist in the data | "Which models are we using?" / used before filtering on a name |
| `data_status` | none | Per provider: connected, `data_as_of`, last sync, last error, price list version | "How fresh is this data?" |

**What the model is told.**
- A short server instruction: what the data is, that cost is list price, what isn't covered (cloud marketplace usage, subscriptions), and to always state the date range and freshness.
- Each tool description is 2–4 lines: when to use it, plus one example.

Descriptions are part of the product. They are the only thing the model sees about the server, they cost tokens on every request, and §7 measures them.

## 6. Failure modes

| Situation | System behaviour | What the user sees |
|---|---|---|
| No API keys configured | Server starts; tools return a configuration error | "No provider connected. Set ANTHROPIC_ADMIN_KEY / OPENAI_ADMIN_KEY." |
| One provider's key is missing or invalid | That provider is skipped; `data_status` shows the error | The answer covers one provider and says the other is missing |
| Empty date window | Query returns no rows | "No usage between X and Y." The result explicitly says no data, never a bare zero the model could misread |
| Provider down or rate-limited | Sync retries with back-off, then gives up; serving continues from the store | The answer is marked stale with its `data_as_of` |
| Request too large | Top-N plus "other" | A compact table with a note that the rest was grouped |
| Model calls the wrong tool or uses bad arguments | Arguments are checked against a schema; errors list the valid values | The model corrects itself and calls again |
| Model invents a number | Server computes every total; descriptions tell the model to quote tool output only | Caught by the §7 evaluation, not at runtime |
| Providers disagree | Each provider's own cost data is the truth; estimate vs reported gap is checked daily | Estimated figures are labelled "estimated (list price)" |
| Price list missing a model | Estimated cost left empty for that model, flagged | "Estimated cost unavailable for model X" |
| Signed-in user belongs to no tenant | No tenant file is opened; tools return an access error | "Your account isn't connected to an organisation. Ask your admin." |
| Tenant's key revoked or rotated | Sync fails for that tenant only; error recorded; tenant admin alerted | The answer is marked stale; `data_status` says the key needs reconnecting |
| New tenant still backfilling | Queries run on the data loaded so far | The answer says the backfill is in progress and how far back the data goes |

## 7. Evaluation

- **Unit tests:** adapters (recorded responses), normaliser, time-period resolution, and query layer (fixture database).
- **Isolation tests:** with two fixture tenants, every tool called as tenant A returns none of tenant B's data, including with crafted filters and arguments.
- **Reconciliation:** on real accounts, totals for 3 date ranges match the provider consoles to the cent (reported cost) and exactly (tokens).
- **End-to-end with a model:** a script acting as a minimal host runs 30 realistic questions through Claude with the tools connected. Ground truth comes from SQL run directly against the same frozen fixture database.

  Measured per question:
  - Did the model pick the right tool?
  - Do the numbers match?
  - Are the date range and `data_as_of` stated?
- **Ship bar:** ≥ 90% of answers fully correct, **0 invented numbers**, 100% state the range and freshness.
- **Below the bar:** fix tool descriptions and output shape first, the tools themselves second, and add each failure to the question set.

## 8. Risks and open questions

- **Per-key cost.** We assume the cost APIs don't break down by API key, which makes per-person cost an estimate. Verify against the current API docs.
- **Web search and tool usage** may not be reported per key by both providers. Verify what each usage endpoint returns. If it's missing, tool cost is reported per workspace/project only.
- **The price list goes stale** when providers change prices or release models. Mitigation: a versioned `pricing.yaml`, the reconciliation check, and the "missing model" flag.
- **Departments.** The existing code has an `org_unit` column, but the APIs have no department field. v1 uses workspace/project as the closest stand-in; a proper team mapping is Phase 2.
- **Hosted OAuth.** Which identity provider to use, and whether Claude/Cursor connect to it smoothly. Prototype early.
- **Admin key blast radius.** Admin keys are powerful. Check whether either provider offers read-only admin keys.
- **Provider rate limits and backfill time.** A 90-day backfill for a 1,000-key tenant is ~1.8M rows through paginated endpoints, which could take minutes to hours. Verify page sizes and Admin API rate limits.
- **Tenant de-duplication.** This needs the provider's organisation ID to be readable with an admin key. Verify for both providers.
- **Many tenant files.** Migrations, backups and restores run per file. Fine at 20 tenants; a reason to move to Postgres beyond that.
- **Code vs design.** The current `schema.py` has cost columns only (no tokens, API key or owner) and needs to be extended to match §4.

## 9. Milestones

1. **Week 1:** schema matches §4; time rules and `pricing.yaml`; normaliser tests on synthetic data.
2. **Week 2:** Anthropic and OpenAI adapters plus sync, tested on recorded responses; first real backfill; reconciliation done.
3. **Week 3:** query layer and 3 MCP tools; local stdio server working in Inspector and Claude Desktop.
4. **Week 4:** evaluation script and 30 questions; tune descriptions to the ship bar.
5. **Week 5:** hosted beta: HTTP transport, OAuth, tenant registry, onboarding page, per-tenant files and hourly sync, isolation tests, monitoring.
6. **Week 6:** beta rollout to the first 5–10 tenants; feedback loop and fixes.

## 10. Decisions log

| Decision | Alternative | Reason |
|---|---|---|
| Admin APIs only (Anthropic, OpenAI) | Cloud billing, invoices | Smallest setup that answers most questions; one key per provider |
| List price, not invoice | Invoice reconciliation | No extra data sources needed; labelled clearly in every answer |
| Ignore subscriptions | Add a fixed-cost table | Fixed cost; no insight to be gained from usage data |
| Static `pricing.yaml` | Live pricing fetch | Needed for per-person cost; a versioned file is auditable and needs no fetching |
| Separate ingestion from serving; local DuckDB | Live API calls per question | Faster, protects rate limits, makes evaluation repeatable |
| Sync on start + when stale (local); hourly timer (hosted) | OS task scheduler | No extra setup for users; provider data lags anyway |
| 3 general tools, server-side SQL | Many narrow tools; model-written SQL | Lower token cost, fewer wrong choices, no injection risk |
| Server resolves named periods | Model works out dates | Removes date-calculation errors |
| UTC daily buckets | Organisation's local time zone | Matches how providers report cost |
| v1 = local first, done when hosted with OAuth | Local only | Beta users shouldn't need to install anything |
| 5–20 tenants in v1 | Single organisation | Hosted beta will be tried by several organisations |
| One DuckDB file per tenant | One file with a `tenant_id` column | Isolation by construction, each tenant syncs in parallel, easy per-tenant backup and deletion |
| Re-sync by deleting the re-fetched days, then inserting | Primary-key upsert | No large in-memory index; simple; never double-counts |
| Keys via onboarding page only | Accept keys through a tool | Tool arguments pass through the model and chat logs |
| Raw API responses as Parquet, 90-day retention | Raw JSON in the facts table | Keeps the database ~20× smaller |

## 11. Phase 2: improvements and fixes

- **Departments and chargeback:** a team mapping (key/workspace/project → department, cost centre), chargeback reports by month.
- **More than ~20 tenants:** Postgres (Supabase is a candidate) with row-level security per tenant instead of per-tenant files; scheduled ingestion workers and a job queue; a dedicated secrets manager; more than one server instance; roles (admin vs viewer, own department only).
- **Cost accuracy:** invoice reconciliation, negotiated discounts and credits, long-context and data-residency price multipliers, automated price-list updates.
- **More sources:** Bedrock, Vertex and Azure OpenAI billing; Claude Code and other usage reports; Gemini and other providers; seat subscriptions as fixed-cost lines.
- **Insight:** forecasting, budgets and alerts, anomaly detection, optimisation advice (caching, batching, model choice).
- **Time:** the organisation's local time zone using hourly usage buckets.
- **Our own host:** a branded chat app for executives who don't use Claude or Cursor, with a fixed system prompt and model.
- **Operations:** audit log of questions and tool calls, freshness alerts, backups and retention.
