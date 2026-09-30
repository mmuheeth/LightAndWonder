# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LightAndWonder is a test-automation console for slot games (FortuneOx, HuffNPuffHighRise) running in the Bally/LnW GDK, either on a local simulator or on an EGM. A FastAPI backend drives the game and reads its screen; a React SPA has one tab per capability. The backend is Windows-specific (OBS, NRobot, UNC log shares, `C:\re\...` config paths).

## Commands

Setup (once): `python -m venv backend\.venv`, then `backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt` (pulls in torch and paddlepaddle, so it is large), then `npm install` in `frontend/`. Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env`.

```powershell
.\start.ps1                       # backend :8000 (uvicorn --reload) + Vite :3000, each in a new window

# backend (run from backend/: .env and relative paths resolve against it)
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
.venv\Scripts\python.exe -m pytest                                 # full suite, ~2.5 min
.venv\Scripts\python.exe -m pytest tests\test_paylines.py -k name  # one file / one test
$env:RUN_OCR_ENGINE_TESTS = "1"; .venv\Scripts\python.exe -m pytest tests\test_ocr_engine.py   # real OCR models, ~1 min, skipped by default

# frontend (from frontend/)
npm run dev        # Vite on :3000
npm run build      # tsc -b && vite build
npm run lint       # oxlint (three existing only-export-components warnings in components/ui are expected)
```

There is no backend linter/formatter config and no frontend test runner. API docs are at `http://localhost:8000/docs`.

## Architecture

### The pipeline

Each frontend tab is one stage, and later stages are built on earlier ones:

1. **OBS** (`obs_service`, `obs_window_service`): controls OBS Studio over obs-websocket, takes screenshots of the game window.
2. **GAF** (`gaf_service`, `utils/nrobot.py`): drives the game through `NRobot.Server.exe` (XML-RPC on :8270, which talks Thrift to the game). NRobot is started outside this repo.
3. **ROI** (`roi_service`, `utils/image_crop.py`): crops the game's configured regions (`cash_meter`, `cyclic_message*`, `reels`) out of a screenshot and splits `reels` into tiles. Regions are fractions of the image.
4. **OCR** (`ocr_service`, `utils/ocr_engine.py`, `ocr_parse.py`): PaddleOCR on the meter and cyclic-message crops.
5. **Symbol** (`symbol_service`, `utils/symbol_classifier.py`): a ResNet34 fine-tuned per game on `app/games/<Game>/symbols/<code>/*.png`, naming each reel tile.
6. **Payline** (`payline_service`, `utils/paylines.py`): scores the symbol grid against the paytable.
7. **Game Config** (the PayTables tab; `game_config_service`, `utils/gdk_files.py`, `utils/log_watcher.py`): `LogWatcher` tails the game's client log to learn the active paytable id and spin start/end; the service then parses that paytable's `math.xml`, `gameConfig.cfg` and `winGeometry.xml`. Payline scoring uses this paytable.
8. **Cyclic Messages** (`cyclic_service`, `utils/cyclic_messages.py`): a background task that, once started, follows `LogWatcher` events (spin start/end, result with win amount, `FirstCycleResultsIterationFinishedMsg`, game over) and from each spin's reels stopping screenshots only the `cyclic_message*` ROIs every `CYCLIC_CAPTURE_INTERVAL` s. Messages are told apart by their pixels (`RegionTracker`), each new one is read by the shared OCR engine in the background, and a round per spin is saved under `obs-captures/obs/cyclic/<id>/`.

Services are built on each other (OCR and Symbol on OBS/ROI/GAF, Payline on Symbol and Game Config, Cyclic Messages on OBS, the log watcher and the OCR engine), so they must share instances. That wiring is all in `backend/app/api/dependencies.py`.

### Backend layering

`api/routes/*` → `controllers/*` → `services/*` → `utils/*`. Routes are thin and declare `Depends(get_xxx_controller)`. Controllers are near pass-throughs. Services hold the logic, state and file I/O. `utils/` is framework-agnostic helpers (several docstrings say what they deliberately do not know about).

- **Dependency injection is `@lru_cache` factories in `api/dependencies.py`**, so each controller/service is a process-wide singleton. That is deliberate: services keep OBS connections, loaded models, training jobs and the NRobot session. A new service that depends on another must take it from those factories, not construct its own. Tests replace them with `app.dependency_overrides[get_xxx] = lambda: ...` (see `tests/conftest.py`).
- Every response is `ApiResponse[T]` (`schemas/response.py`): `ApiResponse.ok(data=..., path=str(request.url.path))`. Failures raise `AppException` subclasses (`core/exceptions.py`); `middleware/error_handler.py` turns them, validation errors and unhandled errors into the same envelope.
- Relative paths in `Settings` (`config/settings.py`) are resolved against `backend/`, not the cwd, via `_backend_path`. `.env` itself is read from the cwd.
- Runtime artefacts are gitignored: `backend/data/` (selected game, OBS config, trained models) and `backend/obs-captures/obs/{screenshots,roi,ocr,symbols}/` (each ROI/OCR capture is a folder `<id>/` with images and `record.json`; ids sort by time).
- `torch` and PaddleOCR are imported lazily because they are slow to load. Keep it that way when touching those services.

### Games

A game is a folder `backend/app/games/<Game>/` containing `<Game>.py` with one config dict whose `"name"` equals the folder name (`utils/game_config.load_game_config` finds the dict by that entry, not by variable name). It has a section per mode, `simulator` and `egm` (host/port, `roi` fractions, `logs`, `game_config`, `win_geometry` paths), plus `symbols`, `reel_bounds`, `wild_card_replacement`, `gaf`, and so on. `GameContextService` lists games by scanning this directory (folders starting with `_` or `.` are skipped) and persists the selected game and mode; nearly every endpoint defaults to that selection.

GAF needs the complete dictionary of object names, so a game's `ObjectQuery.json` only lists differences. `utils/gaf_objects.py` deep-merges it over the vendored base in `app/games/_common/gaf/<game_type>/{general,generic}/`.

### Frontend

Vite + React 19 + TypeScript, Tailwind v4, shadcn/ui (radix-nova) in `components/ui/`, path alias `@/` → `src/`. Per feature there is `api/<x>.ts` (axios calls, unwrapped with `unwrap()` from `api/client.ts`, which throws `ApiRequestError` from the error envelope), `hooks/use<X>.ts` (TanStack Query; polling via `refetchInterval`), `types/<x>.ts` (mirrors the backend schemas by hand) and `components/<x>/<X>Panel.tsx`. Zustand holds only the game/mode selection. The app is called Endurance (the LED-matrix "E" logo in the sidebar is `public/endurance.svg`; the browser-tab favicons are the Light & Wonder mark from lnw.com on a white tile; the Light & Wonder wordmark and mark in the sidebar footer are `public/lightandwonder-logo.svg` and `lightandwonder-mark.png`). Routing is hand-rolled: a tab is an entry in a group of `NAV_GROUPS` in `components/layout/navTabs.ts` (value = URL path, label, icon, one-line description; groups are Tools, Features, Setup, Reference) plus a branch in the `App.tsx` chain. The tabs are a vertical `Sidebar`, with a heading per group; `PageHeader` shows the active tab's title and the game/mode selectors. Every panel is built from the same pieces so the pages stay alike: a top `Card` with the action, then `Section` (title, meta, actions) for results, `Notice` for errors and warnings, `EmptyState` for nothing-yet and loading, and `SubHeading` for labels inside a card (`components/layout/Section.tsx`, `components/ui/notice.tsx`). The palette is neutral graphite; depth comes from the `shadow-card`/`shadow-raised` tokens and the `surface` utility in `index.css`, so use those rather than colour or ring borders. The axios default timeout is 10 s, so slow calls (screenshot + classify) override it per request.

## Things that bite

- **GAF runs one keyword at a time.** NRobot shares a single Thrift connection to the game; two concurrent keywords corrupt it and NRobot then blocks 10-27 s reconnecting. `GafService` serialises with an `_io` lock and reports `busy` rather than queueing. Do not add a second client, script or backend that talks to the same game while the tab is polling.
- **Editing any backend `.py` while a symbol model trains kills the training**, because uvicorn `--reload` restarts the server and training runs in a daemon thread.
- **OCR uses worker processes ("lanes", `OCR_LANES`, ~650 MB each), not threads**, since threads do not scale with Paddle here. Capture size matters: at ~766 px game-window width small labels are misread, so prefer fixing the OBS canvas over adding OCR tricks.
- **Cyclic messages (FortuneOx, measured):** no win: only `cyclic_message_2` cycles (Game Over, Game Pays 0, Play N Credits, ~2.06 s per message, ~1.5 s on show, ~0.5 s blank). Win: `cyclic_message` shows `Game Pays N` then `Line 1 Pays X`; on a 1-2 line win it then holds Line 1 until the win is collected, but a 40-line win stepped through all its lines (and round again) while still held. The lower line only starts once the win is collected (`GameOverMsg`). The spin log's `AttractStartedMsg` / `AttractSequenceEndCompleted` are the no-credits attract mode, unrelated. A win can pay on up to 40 lines (~2 s each, so ~80 s before the first line comes round again), and some lines are nearly indistinguishable at a 766 px capture (`Line 16 Pays 80` / `Line 19 Pays 80`: the most alike pair differs by 33 brightness levels on 16 pixels). `RegionTracker` therefore compares frames strictly (`DIFF_LUMA`; frames of one message are bit-identical), and `tests/fixtures/cyclic/forty_lines/` holds the real crops of such a win as a regression test: a looser limit once merged 3 lines of 40. A win also draws effects across the message line (a yellow sparkle), so only near-white pixels count as text and frames are compared only around the text (`tests/fixtures/cyclic/sparkle/`): comparing the whole crop made one message two, and a false repeat. Each line is followed for one loop: the lines of the win (the areas that changed at least twice before the game went idle) stop on `FirstCycleResultsIterationFinishedMsg` (the game's own "first pass over the winning lines is done", logged when the first line is about to come round again; sent whether or not the win is collected) and are not followed into a second loop, while the round stays open until the lower line, which only starts once the win is collected, has had its loop (screenshots slow to `HOLD_CAPTURE_INTERVAL` meanwhile). An uncollected win is waited for up to 10 min, and a round gets up to 5 min once the game is idle.
- Every backend `.py` edit makes `--reload` restart the backend, which drops its OBS connection and GAF session until Connect is pressed again in those tabs.
- CORS only allows `http://localhost:3000` and `127.0.0.1:3000`. A Vite instance that lands on another port will fail every API call.
- Symbol artwork (`app/games/*/symbols/`) is gitignored and exists only on the machine that has it; games with fewer than 5 images per symbol cannot be validated by the classifier.
- Tests never touch OBS, NRobot or the game: they use `tests/fake_obs.py`, `tests/fake_gaf.py`, `tests/ocr_stub_lane.py` and the real crops in `tests/fixtures/ocr/`.

## Working here

- The user normally already has the backend (:8000, `--reload`) and Vite (:3000) running, with OBS and the game up. Do not start additional servers on other ports or kill processes by pattern; verify backend work with pytest, `TestClient` and scripts on saved captures, and tell the user what to restart or click if something can only be seen in their running UI.
- Other Claude sessions may edit this working tree at the same time. Run `git status --short` before writing new files, and if files you did not write appear, coordinate before continuing.
- Anything that captures (`POST /symbols/identify`, `/paylines/evaluate`, `/roi/records`, OCR) needs OBS connected in the running backend and writes under `backend/obs-captures/`. `GET /api/v1/paylines/score?reading=<id>` re-scores a saved reading without OBS or the game.
