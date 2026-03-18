# Sports Data API Research: CLI Schedule Checker

**Task:** Evaluate sports data APIs for a Python CLI tool (`sandy sports schedule`) that returns the next upcoming game for:
- Baseball: Boston Red Sox (MLB)
- US Football: New England Patriots (NFL)
- Basketball: Boston Celtics (NBA)
- Hockey: Boston Bruins (NHL)
- Soccer: Everton (Premier League)

**Date:** 2026-03-17

---

## Executive Summary

**Recommendation Ranking:**

1. **Top Choice: Hybrid Multi-Endpoint Approach** (ESPN hidden API + nba_api + official MLB/NHL)
   - Zero cost, no API keys needed
   - Full coverage for all 5 sports
   - Most mature Python ecosystem (nba_api, nhlapi packages)
   - Trade-off: ESPN is unofficial; mitigate with caching + fallbacks

2. **Strong Alternative: API-Sports (api-sports.io)**
   - Single API key, covers all 5 sports
   - Free tier: 100 requests/day
   - Rate limits predictable; reliability guaranteed
   - Trade-off: 100 req/day is tight for real-time updates across 5 teams; paid tiers start $19/month

---

## Detailed API Evaluation

### 1. ESPN Hidden API

**Auth:** None required
**Coverage:** All major US sports + soccer
**Reliability:** ⚠️ **Unofficial** — No stability guarantee; ESPN can change/remove endpoints anytime
**Rate Limits:** Undocumented; implement caching and exponential backoff
**Python SDK:** Community-maintained (not official)

**Endpoints:**
- `/apis/site/v2/sports/baseball/mlb/scoreboard` — MLB games
- `/apis/site/v2/sports/football/nfl/scoreboard` — NFL games
- `/apis/site/v2/sports/basketball/nba/scoreboard` — NBA games
- `/apis/site/v2/sports/hockey/nhl/scoreboard` — NHL games
- `/apis/site/v2/sports/soccer/epl/scoreboard` — Premier League games

**Practical Considerations:**
- Community-driven GitHub repos track endpoint changes
- Best for: Low-traffic apps that can tolerate occasional breakage
- **Use if:** You're willing to implement strong error handling and fallbacks

**Sources:** [ESPN Hidden API Guide](https://zuplo.com/learning-center/espn-hidden-api-guide), [Public-ESPN-API Repo](https://github.com/pseudo-r/Public-ESPN-API)

---

### 2. TheSportsDB

**Auth:** Free API key = `"123"` (hardcoded)
**Coverage:** All 5 sports
**Reliability:** ✅ Stable, well-established
**Rate Limits:** 30 requests/minute free tier; up to 100/min on paid tier ($9/month)
**Python SDK:** Community wrappers exist

**Free Tier Constraints:**
- `eventsnext.php?id={teamId}` — Limited to 1 event per request
- `eventslast.php?id={teamId}` — Limited to 1 event, home games only
- `eventsday.php?d={date}` — Max 5 events per day

**Critical Limitation:** Free tier only returns **1 event** for next/previous queries. You'd need to make sequential requests to see multiple upcoming games.

**Example Flow:**
```
/eventsnext.php?id={teamId} → returns next 1 game
/eventsday.php?d={date}&l={leagueId} → returns up to 5 games for a specific date
```

**Verdict:** Workable but inefficient for your use case (need rolling window of ~2 weeks to filter out-of-season teams).

**Sources:** [TheSportsDB Documentation](https://www.thesportsdb.com/documentation), [Free Sports API](https://www.thesportsdb.com/free_sports_api)

---

### 3. nba_api (Python Package)

**Auth:** None required
**Coverage:** NBA only (Celtics only)
**Reliability:** ✅ Stable; wraps official NBA.com APIs
**Rate Limits:** None published; low load expected (small user base)
**Python SDK:** ✅ Excellent; purpose-built for NBA data

**Key Endpoints:**
- `TeamGameLogs` — Retrieve team game history with date filters
- `Scoreboard` — Live game data (from `/live/nba/endpoints`)
- Supports pandas DataFrames, JSON, dict output

**Usage Example:**
```python
from nba_api.stats.endpoints import TeamGameLogs
gamelogs = TeamGameLogs(team_id_nullable='1610612738', season_nullable='2025-26')
df = gamelogs.get_data_frames()[0]
```

**Trade-off:** NBA-only solution; you'd still need other APIs for the other 4 sports.

**Note:** `TeamGameLogs` was briefly deprecated but recently restored due to integration test improvements.

**Sources:** [nba_api PyPI](https://pypi.org/project/nba_api/), [GitHub Repo](https://github.com/swar/nba_api), [TeamGameLogs Endpoint Docs](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/teamgamelogs.md)

---

### 4. Official League APIs

#### MLB (statsapi.mlb.com)

**Auth:** None required
**Coverage:** MLB only (Red Sox only)
**Reliability:** ✅ Official; stable
**Python SDK:** None (use raw HTTP)

**Endpoints:** Not fully documented in public; includes schedule endpoints at `/api/v1/schedule`

**Trade-off:** MLB-only; undocumented public API means trial-and-error integration

**Sources:** [MLB Stats API](https://statsapi.mlb.com/), [Docs](https://docs.statsapi.mlb.com/)

---

#### NHL (statsapi.web.nhl.com)

**Auth:** None required
**Coverage:** NHL only (Bruins only)
**Reliability:** ✅ Official; stable
**Python SDK:** Community wrapper `nhl-api-py` available

**Endpoints:**
- `GET /api/v1/schedule` — Returns full schedule (queryable by date range + team)
- `GET /api/v1/schedule?teamId=6&startDate=2026-03-17&endDate=2026-04-17` — Team schedule filtered by date

**Example:**
```
GET https://statsapi.web.nhl.com/api/v1/schedule?teamId=6&startDate=2026-03-17&endDate=2026-04-17
```

**Verdict:** Excellent for Bruins; zero auth, well-documented, stable.

**Sources:** [NHL API Reference](https://github.com/Zmalski/NHL-API-Reference), [dword4/nhlapi](https://github.com/dword4/nhlapi)

---

#### NFL (Official API)

**Auth:** No official public API exists
**Alternatives:**
- ESPN hidden API (covered above)
- MySportsFeeds (see below)
- Sportradar (requires key)

**Verdict:** Must use third-party service for Patriots schedule.

**Sources:** [MySportsFeeds](https://www.mysportsfeeds.com/data-feeds), [SportsDataIO](https://sportsdata.io/developers/api-documentation/nfl)

---

### 5. Premier League / Soccer APIs

#### API-Football (api-sports.io)

**Auth:** Free API key (register for free)
**Coverage:** 1200+ leagues including Premier League
**Reliability:** ✅ Stable; commercial provider
**Rate Limits:** **100 requests/day** free tier
**Python SDK:** Community wrappers exist

**Endpoints:**
- `GET /fixtures?team={teamId}&season={year}&league={leagueId}` — Team fixtures filtered
- Supports date range filtering, status filtering (scheduled/played)

**Key Issue:** 100 requests/day is **extremely tight** for monitoring 5 teams across all sports. Single schedule check costs 1-5 requests depending on parameters.

**Verdict:** Better for focused monitoring of one league, not ideal for multi-sport dashboard.

**Sources:** [API-Football Pricing](https://www.api-football.com/pricing), [Documentation](https://www.api-football.com/documentation-v3), [Fixtures Endpoint Guide](https://www.api-football.com/news/post/how-to-get-all-fixtures-data-from-one-league)

---

#### football-data.org

**Auth:** Optional free API key (10 req/min); 100 req/24h unauthenticated
**Coverage:** Premier League + 500+ competitions
**Reliability:** ✅ Stable; academic/community project
**Rate Limits:** 10 req/min with free key; 30/min standard
**Python SDK:** Community wrappers available

**Endpoints:**
- `GET /competitions/PL/matches?matchday={day}` — Premier League matches by matchday
- No explicit team ID filtering in free tier; fetch all PL matches and filter locally

**Verdict:** Good alternative to API-Football if you don't need real-time. Free tier is usable.

**Sources:** [football-data.org API Reference](https://www.football-data.org/documentation/api), [Quickstart](https://www.football-data.org/documentation/quickstart)

---

### 6. MySportsFeeds

**Auth:** Free tier for personal/non-commercial use (API key required)
**Coverage:** NFL, MLB, NBA, NHL only (no soccer)
**Reliability:** ✅ Commercial provider; stable
**Rate Limits:** Not specified in free tier; 14-day trial available
**Python SDK:** None official; use REST client

**Format:** XML, JSON, CSV output

**Critical Gap:** **No Premier League / soccer coverage.** Not viable for your use case.

**Sources:** [MySportsFeeds](https://www.mysportsfeeds.com/data-feeds), [Pricing](https://www.mysportsfeeds.com/feed-pricing/)

---

### 7. BALLDONTLIE

**Auth:** Free API key (register)
**Coverage:** 20+ leagues across all sports (NBA, NFL, MLB, NHL, EPL, etc.)
**Reliability:** ✅ Stable; modern commercial API
**Rate Limits:** **5 requests/minute free tier** ⚠️ **Very restrictive**
**Python SDK:** None official

**Critical Limitation:** 5 req/min is insufficient. Checking 5 teams sequentially would take 1+ minutes.

**Verdict:** Good coverage but prohibitive rate limits for free tier.

**Sources:** [BALLDONTLIE](https://www.balldontlie.io/), [Rate Limits](https://www.balldontlie.io/blog/getting-started/)

---

## Comparison Matrix

| API | Auth | MLB | NFL | NBA | NHL | Soccer | Free Tier | Rate Limit | Reliability | Python SDK |
|-----|------|-----|-----|-----|-----|--------|-----------|-----------|--------------|-----------|
| **ESPN** | None | ✅ | ✅ | ✅ | ✅ | ✅ | Unlimited | None (undoc) | ⚠️ Unofficial | Community |
| **TheSportsDB** | Free key | ✅ | ✅ | ✅ | ✅ | ✅ | Limited* | 30/min | ✅ Stable | Community |
| **nba_api** | None | ❌ | ❌ | ✅ | ❌ | ❌ | Unlimited | None | ✅ Stable | ✅ Excellent |
| **MLB Official** | None | ✅ | ❌ | ❌ | ❌ | ❌ | Unlimited | None | ✅ Stable | ❌ No |
| **NHL Official** | None | ❌ | ❌ | ❌ | ✅ | ❌ | Unlimited | None | ✅ Stable | Community |
| **API-Football** | Free key | ❌ | ❌ | ❌ | ❌ | ✅ | **100/day** | 100/day | ✅ Stable | Community |
| **football-data.org** | Free key | ❌ | ❌ | ❌ | ❌ | ✅ | 10/min | 10/min | ✅ Stable | Community |
| **MySportsFeeds** | Free key | ✅ | ✅ | ✅ | ✅ | ❌ | Limited | Undoc | ✅ Stable | ❌ No |
| **BALLDONTLIE** | Free key | ✅ | ✅ | ✅ | ✅ | ✅ | **5/min** | 5/min | ✅ Stable | ❌ No |

*TheSportsDB free tier: 1 next/previous event per request, inefficient for rolling schedule window.

---

## Recommendation #1: Hybrid Multi-Endpoint Approach (Preferred)

**Best for:** Zero cost, full coverage, leveraging best-of-breed APIs per sport.

### Architecture

```
Sandy CLI Schedule Checker
├── MLB (Red Sox)        → statsapi.mlb.com (official, no auth)
├── NFL (Patriots)       → ESPN hidden API (no auth)
├── NBA (Celtics)        → nba_api Python package (no auth)
├── NHL (Bruins)         → statsapi.web.nhl.com (official, no auth)
└── Soccer (Everton)     → football-data.org (free key required)
```

### Implementation Notes

1. **Cache aggressively:** ESPN can change; local cache prevents cascading failures
2. **Fallback chain:** ESPN → TheSportsDB for NFL if ESPN fails
3. **Date window:** Query 2 weeks ahead to filter out-of-season teams (per requirements)
4. **Local time conversion:** Handle timezone conversion to system local time

### Pros
- **Zero monetary cost**
- **Official or well-maintained APIs** for 4/5 sports
- **Python ecosystem:** nba_api + community wrappers handle most integration
- **No single point of failure:** Different provider per sport
- **Mature endpoints:** These APIs have been stable for years

### Cons
- **ESPN risk:** Unofficial; must implement robust error handling + caching
- **Integration complexity:** 5 different API shapes to normalize
- **football-data.org:** Requires free key + local filtering of matches

### Implementation Priority

1. Start with official APIs (NHL, MLB)
2. Add nba_api for Celtics
3. Add ESPN for Patriots (simplest no-auth NFL option)
4. Add football-data.org for Everton (requires registration but stable)

---

## Recommendation #2: API-Sports (Single Provider)

**Best for:** Simplicity, guaranteed reliability, willing to pay.

### Setup

```
API-Sports (api-sports.io)
├── Free tier: 100 requests/day
├── Auth: Single API key
└── Coverage: All 5 sports (NFL, MLB, NBA, NHL, EPL)
```

### Pros
- **Single integration:** One API, unified endpoint structure
- **All-in-one:** Zero setup complexity; register once, use everywhere
- **Reliability:** Commercial provider; SLA available on paid tiers
- **Predictable rate limits:** 100 req/day transparent
- **Paid upgrade path:** $19/month → reasonable rates for scaling

### Cons
- **100 req/day tight for production:** One schedule check per team = 5 req/day; leaves little headroom for caching strategy or retries
- **Cost:** Free tier insufficient; realistically need paid tier ($19/mo minimum)
- **Not ideal for:** Real-time monitoring across multiple teams

### When to Use
- If you want guaranteed uptime + commercial support
- If you're okay paying $19-50/month
- If you want to avoid integrating 5 different APIs

---

## Decision Framework

**Choose Hybrid (#1) if:**
- You want zero ongoing cost ✅
- You're comfortable managing multiple API integrations ✅
- You can implement fallback/caching logic ✅
- You're building a hobby/personal tool (not production SLA required) ✅

**Choose API-Sports (#2) if:**
- You want simplicity over cost ✅
- You need SLA/reliability guarantees ✅
- You're building for commercial use ✅
- You can budget $19-50/month ✅

---

## Integration Priority for Hybrid Approach

### Phase 1: Core Foundation (All 4 Official/Stable APIs)
1. **NHL:** `statsapi.web.nhl.com` — Bruins schedule
2. **MLB:** `statsapi.mlb.com` — Red Sox schedule
3. **NBA:** `nba_api` package — Celtics schedule
4. **Soccer:** `football-data.org` — Everton schedule (free key)

### Phase 2: Add NFL with Fallback
1. **Primary:** ESPN hidden API — Patriots schedule
2. **Fallback:** TheSportsDB if ESPN fails

### Phase 3: Production Hardening
1. Implement 1-hour cache (TTL) for each sport
2. Add comprehensive error handling + logging
3. Monitor ESPN endpoint changes (GitHub watchers)
4. Add fallback chains per sport

---

## Implementation Checklist

- [ ] Register for free keys: `football-data.org`, `api-sports.io` (keep as backup)
- [ ] Install Python packages: `pip install nba_api requests pandas`
- [ ] Clone/ref NHL API repo: `github.com/dword4/nhlapi`
- [ ] Implement cache layer (e.g., `functools.lru_cache` with TTL)
- [ ] Write integration tests for each API endpoint
- [ ] Document endpoint URLs and parameters
- [ ] Handle timezone conversion to local time
- [ ] Add 2-week lookahead filter to detect out-of-season teams

---

## References

**Official APIs & Documentation:**
- [MLB Stats API](https://statsapi.mlb.com/) | [Docs](https://docs.statsapi.mlb.com/)
- [NHL Stats API](https://statsapi.web.nhl.com/api/v1/) | [Reference](https://github.com/Zmalski/NHL-API-Reference)
- [NBA Stats (via nba_api)](https://github.com/swar/nba_api)
- [football-data.org API](https://www.football-data.org/documentation/api)

**Third-Party/Community APIs:**
- [ESPN Hidden API](https://github.com/pseudo-r/Public-ESPN-API)
- [TheSportsDB](https://www.thesportsdb.com/free_sports_api)
- [API-Sports (api-sports.io)](https://api-sports.io/)
- [BALLDONTLIE](https://www.balldontlie.io/)
- [MySportsFeeds](https://www.mysportsfeeds.com/data-feeds)

**Python Packages:**
- [nba_api PyPI](https://pypi.org/project/nba_api/)
- [nhl-api-py PyPI](https://pypi.org/project/nhl-api-py/)
- [thesportsdb PyPI](https://pypi.org/project/thesportsdb/)
