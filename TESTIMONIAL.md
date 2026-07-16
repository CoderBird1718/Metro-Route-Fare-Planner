# TESTIMONIAL

## Overall Approach

I started by reading `INSTRUCTIONS.md` and `README.md` end-to-end before touching any code, then walked the codebase top-down: backend entry point (`main.py`) → routes (`routes.py`) → services (`graph_engine.py`, `unlock_service.py`) → DB clients (`sqlite_client.py`, `postgres_client.py`) → frontend (`App.jsx` → components → `services/api.js`). I also read `database_setup/sqlite_ddl_description.md` carefully before writing any routing logic, since the graph model (separate node per line, directed `connections`, one-way-but-mirrored `interchanges`) directly shapes how Dijkstra needs to traverse the data.

Once I understood the shape of the system — PostgreSQL for transactional/config data, SQLite for the static metro graph, a background cron thread that keeps a heartbeat, and an AES-encrypted "verification code" that only unlocks once both DB fragments and a fresh heartbeat are present — I fixed the app in dependency order: environment → SQLite access → backend endpoints → frontend wiring.

## Bugs Found & How I Fixed Them

1. **Missing `sqlalchemy` dependency.** `postgres_client.py` and `routes.py` import `sqlalchemy`, but it wasn't listed in `backend/requirements.txt`, so the app failed to boot immediately. Added `sqlalchemy>=2.0.0`.

2. **Broken SQLite path resolution.** `sqlite_client.py` built its path as `Path(__file__).resolve() / "metadatagraph.db"` — appending a filename onto a *file* path instead of its parent directory, and misspelling the filename (missing the underscore in `metadata_graph.db`). Fixed to `Path(__file__).resolve().parent / "metadata_graph.db"`.

3. **CORS origin mismatch.** `main.py` only allowed `http://localhost:3000`, but the Vite dev server (per `vite.config.js` and the README) runs on port `5173`. Every frontend API call would have been blocked by the browser. Updated `allow_origins` to include `http://localhost:5173`.

4. **Frontend API base URL pointed at the wrong port.** `services/api.js` defaulted to `http://localhost:8080/api`, but the backend (per the README's uvicorn command and `main.py`) runs on port `8000`. Fixed the default to `http://localhost:8000/api`.

5. **Missing `lucide-react` dependency.** `App.jsx`, `RouteSelector.jsx`, `SystemStatus.jsx`, and `Dashboard.jsx` all import icons from `lucide-react`, but it wasn't declared in `frontend/package.json`, so `npm install` wouldn't pull it in and the app would fail to build. Added it to `dependencies`.

6. **Malformed `DATABASE_URL` in `.env.example`.** It read `postgresql://postgres:postgres@localhost5432/kolkata_metro` — missing the colon before the port — which would break Postgres connections for anyone copying the example file. Fixed to `localhost:5432`.

7. **`/allstations` endpoint was a stub (`pass`).** Implemented it to open a SQLite connection, select `id, name, line` from `stations`, and return them ordered by line/name so the frontend dropdowns group sensibly.

8. **`/route` route-finding logic was entirely unimplemented (`pass` in `graph_engine.py`).** This was the core task. I implemented:
   - A graph loader that reads `stations`, `connections` (ride edges, weighted by `travel_time_minutes`, carrying `fare_inr`), and `interchanges` (walking edges, weighted by `transfer_time_minutes`, no fare) into an adjacency list.
   - A **multi-source Dijkstra**: because interchange stations (e.g. Park Street, Esplanade) exist as *separate rows per line* with the same name, I treat every station-name match as a valid start/end node and run Dijkstra from all of them simultaneously, then pick whichever destination-line node is cheapest to reach. This avoids forcing the caller to know which specific line variant of a station to start from.
   - Path reconstruction that walks the `prev` map back from the destination node to the source, then builds the `ordered_itinerary` the frontend already expected (`station_name`, `line`, `is_interchange`, `transfer_to`), while summing `total_fare_inr`, `total_travel_time_minutes`, and `interchanges_count` for `route_summary`.
   - I deliberately did **not** touch the existing `/route` endpoint signature, its query params, or the response contract — only filled in the function body of `get_metro_route`, as instructed.

## Frontend Integration

The frontend components (`RouteSelector.jsx`, `Dashboard.jsx`, `SystemStatus.jsx`) already contained working calls to `getAllStations()` and `getRoute()` and already rendered `route_summary` / `ordered_itinerary` in the expected shape, so once the backend was fixed and returning real data, the existing UI displayed the station list (via the searchable source/destination dropdowns) and the computed shortest route (fare, travel time, interchange count, and a stop-by-stop itinerary with transfer callouts) without further changes needed on my end. I verified this by hitting the API directly and cross-checking the JSON shape against what the components destructure.

## Challenges

- The multi-line interchange-station modeling (same name, multiple line-scoped rows) was the trickiest part of the route logic — a naive single-source Dijkstra keyed only by station ID would force the caller to disambiguate which line-variant of a station to start from, which the frontend (and the assignment's test cases, e.g. Park Street → Howrah) doesn't do. Multi-source Dijkstra solved this cleanly without changing the API contract.
- Several bugs were "silent" in the sense that they wouldn't show a stack trace until you tried the *next* step (e.g., the CORS/port mismatches only surface as browser network errors, not backend crashes), so I made a point of testing every endpoint directly with `curl` before trusting the frontend.

## Assumptions Made

- Assumed "shortest route" means shortest by **travel time** (as stated in the docstrings and the DDL's "Shortest path algorithms" framing), with fare and interchange count reported as secondary metrics rather than used as the optimization target.
- Assumed interchange edges have zero fare (consistent with the DDL, where only `connections` has a `fare_inr` column).
- Assumed the frontend's existing response-shape expectations (`route_summary`, `ordered_itinerary` with `is_interchange`/`transfer_to`) were the intended contract to satisfy, since the instructions say not to change the API contract and the frontend was already coded against this shape.

## Improvements With More Time

- Add automated tests (pytest) for `get_metro_route`, especially edge cases: same-name different-line source/destination, unreachable stations, and unknown station names.
- Add a dedicated loading/error state distinction in the UI between "stations failed to load" and "route failed to calculate" (currently both surface as a generic error banner).
- Cache the SQLite graph in memory at startup instead of re-reading all three tables on every `/route` call, since the topology is static.
- Add input validation/normalization (trim/case-insensitive match) for station names in `get_metro_route` to make the endpoint more forgiving of minor client-side formatting differences.
