# User Interaction Flow

How the buy-side agent handles a live LLM conversation from setup through conversion feedback.

## Phase 0 — Advertiser setup (once)

Before any user sees ads, the advertiser onboards their brand.

```mermaid
flowchart TD
    Adv[Advertiser] -->|website URL + notes| Onboard[POST /api/brand/onboard]
    Onboard --> TavilyExtract[Tavily Extract API]
    TavilyExtract -->|markdown content| Parse[Parse brand profile]
    Parse --> Plan[Ad plan draft]
    Plan --> Store[(brands.json)]
    Plan --> Suggest[suggested_catalog products + creatives]
    Plan --> Guide[creative_guidelines + guardrails]
    Adv -->|optional activate=true| Activate[POST /api/brand/id/activate]
    Activate --> ActiveCatalog[Agent uses brand catalog]
```

Tavily [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract) scrapes the advertiser's site; the agent infers voice, keywords, value props, and draft products/creatives. See [Tavily docs](https://docs.tavily.com/welcome).

---

## Phase 1 — User message arrives

A user sends a prompt inside an LLM chat (ChatGPT-style placement, Thrad app, etc.).

```mermaid
flowchart LR
    User[User prompt in LLM chat] --> Gateway[Placement SDK / API]
    Gateway --> Decide[POST /api/decide]
```

---

## Phase 2 — Fast path (under ~500ms)

Intent and ranking run without TribeV2.

```mermaid
flowchart TD
    Decide[POST /api/decide] --> Intent[Extract intent cluster]
    Intent --> Rank[Rank products vs user prompt]
    Rank --> Catalog{Active brand catalog?}
    Catalog -->|yes| BrandProducts[Brand suggested_catalog]
    Catalog -->|no| DefaultProducts[Default catalog.json]
    BrandProducts --> Candidates[Top K products x 2 creatives]
    DefaultProducts --> Candidates
    Candidates --> Filter[Drop paused creatives]
    Filter --> Finalists[Top 3 finalists]
```

---

## Phase 3 — Slow path (finalists only)

TribeV2 and Tavily run only on the top 3 candidates (~30–60s total with caching).

```mermaid
flowchart TD
    Finalists[Top 3 finalists] --> UserTribe[TribeV2: score user context once]
    Finalists --> AdTribe[TribeV2: score each ad copy cached]
    Finalists --> TavilySearch[Tavily Search: market context]

    UserTribe --> Fit[Emotional fit OFC PCC insula ACC]
    AdTribe --> Fit
    TavilySearch --> Urgency[Price reviews competitor signals]

    Fit --> PCVR[p conversion model]
    Urgency --> PCVR
    IntentScore[intent_score] --> PCVR
    Bandit[bandit bonus from past outcomes] --> PCVR
```

---

## Phase 4 — Bid decision and gates

```mermaid
flowchart TD
    PCVR[p_cvr] --> EV[EV = p_cvr x value - bid]
    EV --> Floor{p_cvr >= floor?}
    Floor -->|no| NoBid[no_bid save budget]
    Floor -->|yes| Safety{Brand safety OK?}
    Safety -->|no| NoBid
    Safety -->|yes| Insula{Insula spike?}
    Insula -->|yes| Escalate[escalate HITL]
    Insula -->|no| NewCreative{First serve of creative?}
    NewCreative -->|yes| Escalate
    NewCreative -->|no| Spend{Spend spike?}
    Spend -->|yes| Escalate
    Spend -->|no| Serve[Serve ad in LLM channel]
```

---

## Phase 5 — After serve (learning loop)

```mermaid
flowchart TD
    Serve[Served ad] --> Imp[impression logged]
    Imp --> Click{User clicks?}
    Click -->|no| NoClick[no_click event]
    Click -->|yes| Conv{Converts?}
    Conv -->|yes| Conversion[conversion event]
    Conv -->|no| ClickOnly[click only]

    NoClick --> BanditDown[Decay bandit weight]
    ClickOnly --> BanditSmall[Small bandit adjust]
    Conversion --> BanditUp[Boost bandit weight]

    NoClick --> PauseCheck{3+ imps 0 clicks?}
    PauseCheck -->|yes| Pause[Pause creative]
    Pause --> EscQueue[Escalation queue]
```

Report outcomes via `POST /api/outcome` with `placement_id` and event type.

---

## End-to-end (single diagram)

```mermaid
flowchart TB
    subgraph setup [Setup once]
        A1[Advertiser website] --> A2[Tavily Extract]
        A2 --> A3[Ad plan + catalog]
    end

    subgraph live [Per user message]
        B1[User prompt] --> B2[Intent rank]
        B2 --> B3[Top 3 finalists]
        B3 --> B4[TribeV2 + Tavily]
        B4 --> B5[p_cvr and bid]
        B5 --> B6{Gates}
        B6 -->|serve| B7[Ad in LLM chat]
        B6 -->|no_bid| B8[Skip placement]
        B6 -->|escalate| B9[Human review]
    end

    subgraph learn [After serve]
        B7 --> C1[Outcome events]
        C1 --> C2[Bandit update]
        C2 --> B2
    end

    setup --> live
```

---

## API quick reference

| Step | Endpoint |
|------|----------|
| Onboard brand from website | `POST /api/brand/onboard` |
| Activate brand catalog | `POST /api/brand/{id}/activate` |
| Decide on user prompt | `POST /api/decide` |
| Log impression / click / conversion | `POST /api/outcome` |
| Resolve HITL escalation | `POST /api/escalations/resolve` |
| Dashboard metrics | `GET /api/dashboard` |
