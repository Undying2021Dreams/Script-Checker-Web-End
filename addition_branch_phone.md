# addition_branch_phone.md — on-device grading additions

|                  |                                                   |
| ---------------- | ------------------------------------------------- |
| **Branch**       | `feature/on-device-grading`                       |
| **Base**         | `main` @ `c69eea2`                                |
| **Status**       | **ready for review**                              |
| **Last updated** | 2026-09-27 (Session 11, deployed handover; not yet committed) |

## 1. Purpose

A student Android app (Capstone_Android) grades each answer box on the phone with an on-device model: Gemma 4 E2B via LiteRT-LM, in two turns (transcribe the crop without the model answer, then mark the transcript as text). This branch adds the student-side routes it needs:

- download the assignment and its answer key;
- start a grading run and post the phone's marks;
- have the server's self-hosted model re-mark uncertain boxes;
- request re-evaluation.

Teachers keep using the website exactly as before.

## 2. Rules this branch follows

- **Additive only.** No existing route changes behaviour. The frontend is not touched.
- New code lives in its own router file (`backend/routers/on_device.py`), registered under `/api`, with its logic in `backend/services/on_device.py`.
- **One additive migration:** three nullable columns on `submissions`: `on_device_run_token`, `on_device_started_at` and `on_device_posted_at`. With fewer columns, a teacher-started server run can't be told apart from a phone run, and a run waiting on fallback can't be told apart from one that never posted. The phone's raw model reply, including its CONFIDENCE line, goes in the existing `raw_response` column.
- **Demo decision:** the assignment pack sends the answer key to enrolled students before they answer. This is an accepted risk for the capstone demo, not a design for real exams.
- **Deliberate exception:** the new "my grades" route shows students provisional marks before release. Existing student routes still show marks only after release.
- **Status meaning:** a paper stays `grading` until every box is finished, fallback boxes included. The server checks that every box is accounted for.
- The teacher page does not update by itself. The teacher is told through the notification bell and sees the marks on refresh.
- A teacher pressing **Grade** on the website re-marks every unprotected box and overwrites the phone's marks.
- `services/on_device.py` is the second writer of `AnswerGrade` rows, beside `grading_runner.grade_submission`. It writes the same columns and doesn't change `grading_runner.py`.

## 3. Changelog (newest first)

One row per Claude Code session. Claude Code doesn't commit; the branch owner commits these changes and pushes the branch.

| Session | Date | Files | What changed | Why | Tests |
| ------- | ---- | ----- | ------------ | --- | ----- |
| 11 (deployed handover; docs only here) | 2026-09-27 | `addition_branch_phone.md` | Re-audit: `git diff --stat origin/main...HEAD` is empty (the branch has no commits; `HEAD` = `origin/main` = `c69eea2`, checked with `git ls-remote`). Every uncommitted change is listed in §5 and in the Session 3 row; code files unchanged since Session 3 (all dated 2026-09-25). The two `.env.example` deletions are still in the working tree (§5.1). §1: the phone's model is now Gemma 4 E2B, two-turn. §8 rewritten as the deploy checklist for the deployed web end: deploy options (merge, or build the branch), `SELF_HOSTED_LLM_URL` (no `/v1` for the Kaggle cell), `ON_DEVICE_LEASE_MINUTES`, the Android redirect with the actual debug hash, supported account types, `TEACHER_EMAILS` (set only when the app is created; promotion is one-way), a join code, and the values to send back. §6 and §10 brought up to date. No code changed in this repo. | The teammate deploys from this file. | Full suite: **197 passed, 13 failed**, the same 13 as Session 3, all poppler missing on this Windows machine (12 `PDFInfoNotInstalledError`; `test_an_oversized_pdf_page_is_rasterised_down_rather_than_whole` fails because `_pdf_page_dpi` falls back to 300 DPI without `pdfinfo`, `routers/submissions.py:226-227`). `tests/test_on_device.py` all passed. |
| 9, 9b, 9c, 10 | 2026-09-26 | none | No changes in this repo. Phone-side work: Gemma 4 E2B two-turn grading, a "Force server re-mark" debug switch, and fallback testing against the local web end on this branch. | Listed so every session is accounted for. | Local web end, this branch: "Fallback unavailable" passed (Session 9); Gemma two-turn 5/5 and 10/15 posted as `on_device` (Session 9c); forced re-mark came back `self_hosted` (reported by the branch owner, 2026-09-27). |
| 8 (Phase 8, handover; docs only here) | 2026-09-25 | `addition_branch_phone.md` | Status set to **ready for review**. Audit of `git diff main`: every code change is listed in §5 and in the Session 3 row; nothing else changed except the two `.env.example` deletions (§5.1), which are not part of this branch. §4: a "Tested" column per route. §8: full merge and deploy checklist (image build, migration, `ON_DEVICE_LEASE_MINUTES`, Entra Android redirect with the debug and release hash commands, `SELF_HOSTED_LLM_URL`, health check). §10: test coverage summary. No code changed in this repo. | Handover: the teammate should need nothing but this file. | none (docs). `pytest` not re-run this session (no code change since Session 3). |
| 0–2, 5, 6 | 2026-09-25 | none | No changes in this repo. Sessions 0–2 were plan and phone-grading work; 5 and 6 were phone-only (scan, upload, crops, the grading runner). They use this branch's routes and the existing upload and hand-in routes unchanged. | Listed so every session is accounted for. | — |
| 7 (Phase 7, end-to-end test; docs only here) | 2026-09-25 | `addition_branch_phone.md` | §9: two new known risks from the first real phone runs: the printed box label likely counts as ink in `looks_blank` on photos, and the web end read 0 of 2 box QR codes on every phone upload (not investigated). §10: what the end-to-end test exercised on this branch's routes. Header "Last updated". No code changed in this repo. | The user chose to leave `looks_blank` as it is and not to investigate the QR codes; both are recorded instead. | none (docs) |
| 4 (Phase 4, Android sign-in; docs only here) | 2026-09-25 | `addition_branch_phone.md` | §8: the Entra checklist item now spells out the request for the deployed registration's Android redirect (package, debug hash, client id back to the branch owner, release hash later). No code changed in this repo. | The phone app now signs in with MSAL and uses a separate client id per web end: the branch owner's registration for the local web end, the teammate's for the deployed one. Both need the Android redirect. | none (docs) |
| 3 (Phase 3, web end) | 2026-09-25 | `backend/routers/on_device.py` (new), `backend/services/on_device.py` (new), `backend/alembic/versions/a9c4d2e81f37_on_device_runs.py` (new), `backend/tests/test_on_device.py` (new), `backend/models.py`, `backend/schemas.py`, `backend/config.py`, `backend/main.py`, `backend/tests/conftest.py`, `addition_branch_phone.md` | Six student routes (pack, pack images, start, results, my grades, re-evaluation); lease sweeper started with the app; background self-hosted fallback for flagged boxes; `ON_DEVICE_LEASE_MINUTES`; one migration adding three nullable columns; `graded_on_device` and `reevaluation_requested` notifications. `conftest.py` gains one line that turns the sweeper loop off under test. | The phone grades on its own and needs a contract to post marks that the server can check, expire and complete. | `tests/test_on_device.py`: 35 passed. Full suite: 197 passed, 13 failed. All 13 failures are poppler (`pdfinfo`/`pdftoppm`) missing on the Windows dev machine, in `test_print_size`, `test_question_access` (real page renders) and `test_scanning`. None touch this branch's code, and the Dockerfile installs `poppler-utils`. |
| — | — | `addition_branch_phone.md` | File added | Track every change on this branch | — |

## 4. Routes added

All under `/api`, all requiring Microsoft sign-in. Every route requires the caller to be enrolled in the paper's course (`routers/student._assert_enrolled`). The submission routes also require the caller to be the submission's student, and return 404 otherwise, including for the course teacher. `400` errors carry an object, `{"detail": {"message": ..., <ids>}}`.

| Method | Path | Who may call | Purpose | Status | Tested |
| ------ | ---- | ------------ | ------- | ------ | ------ |
| GET | `/api/student/assignments/{question_id}/pack` | enrolled student; finalized papers only (404 otherwise) | Page geometry, markers, boxes with segments, points, question text, **answer key**, image refs, blocked reason | built | pytest (parity with `build_grading_items`, draft 404, not enrolled); phone, Session 7 |
| GET | `/api/student/assignments/{question_id}/pack/images/{kind}/{image_id}` | enrolled student | `kind` = `model-answer` (a `GroundTruthImage` of this paper) or `question` (an `UploadedImage` of this paper). Returns the bytes. | built | pytest (refs resolve relative to the pack); phone, Session 7 |
| POST | `/api/student/submissions/{submission_id}/on-device/start` | owner, after hand-in. Rate limit `LLM_LIMIT` (40/hour). | Sets `grading`, records the start time, returns a run token | built | pytest (not handed in, released, graded, teacher run, restart after expiry); phone, Session 7 |
| POST | `/api/student/submissions/{submission_id}/on-device/results` | owner with the live token. Rate limit `LLM_LIMIT`. | Saves every eligible box (provider `on_device`); fallback for flagged boxes; `graded` once every box is done; notifies the teacher | built | pytest (every box, needs review, protected, missing, range, unknown/duplicate, idempotent, superseded/expired token, fallback off/unset/success/background/superseded, notification); phone, Session 7 (no fallback) |
| GET | `/api/student/submissions/{submission_id}/grades` | owner | Provisional marks and status, before and after release | built | pytest (existing routes stay release-only, teacher sees marks); phone, Session 7 |
| POST | `/api/student/submissions/{submission_id}/re-evaluation` | owner, once `graded`. Rate limit 5/hour. | Notifies the teacher with a link to the paper | built | pytest (notification, rate limit); **not tried from the phone** |

Also added: a background sweeper, started with the app, that marks runs older than the lease as `failed`, so the teacher's **Grade** button works again. Tested by pytest (expires an old run, leaves a live one, lost fallback); **not seen on the phone**.

### 4.1 Pack

```jsonc
{
  "pack_version": 1,
  "question_id": "…", "course_id": "…", "title": "…",
  "page_w_px": 1240, "page_h_px": 1754, "page_count": 2, "dpi": 150,
  "markers": {"aruco_dict": "DICT_4X4_50", "marker_size_px": 60, "marker_margin_px": 40,
              "centres": {"0": [70, 70], "1": [1170, 70], "2": [70, 1684], "3": [1170, 1684]}},
  "boxes": [{
    "id": "a1", "label": "a", "points": 5, "order_index": 0,
    "page_index": 0, "bbox": [x, y, w, h], "segments": [[page, x, y, w, h], …],
    "question_text": "…", "model_answer_text": "…",
    "model_answer_images": ["pack/images/model-answer/<GroundTruthImage.id>"],
    "question_images": ["pack/images/question/<UploadedImage.id>"],
    "blocked_reason": null
  }]
}
```

- `question_text`, `model_answer_text` (the answer key), `points` and `blocked_reason` come from `build_grading_items` itself, run with a stand-in submission that has no crops. The pack therefore can't drift from what a server run uses, and a test checks this.
- Image refs are relative to the pack's own URL. Resolving `pack/images/…` against `…/assignments/{id}/pack` gives the image route. They are never absolute URLs built from `PUBLIC_BASE_URL`.
- `centres` comes from `doc_renderer.get_marker_positions`. It is `{}` if the paper has no page size.

### 4.2 Start

Response: `{run_token, started_at, lease_expires_at, eligible_box_ids, protected_box_ids}`. Eligible means every box minus `protected_answer_box_ids` (released or teacher-overridden).

| State | Result |
| ----- | ------ |
| Not handed in (`submitted_at` null) | 409 |
| Released | 409 |
| `graded` | 409 (ask for re-evaluation instead) |
| `queued`, or `grading` without `on_device_started_at` (a teacher's server run) | 409 |
| `grading`, posted, fallback still running | 409 |
| `ungraded`, `failed` (including an expired run), or the owner's own unposted run | 200, new token, `grading`, error cleared |

### 4.3 Results

```jsonc
{
  "run_token": "…",
  "use_fallback": true,              // the app's fallbackEnabled flag
  "fallback_box_ids": ["a2"],
  "results": [{
    "answer_box_id": "a1",
    "outcome": "scored" | "blank" | "needs_review",
    "score": 3.0,                    // required for scored; ignored otherwise
    "feedback": "…",                 // ≤ 5000 chars
    "confidence": 82,                // 0..100, not stored separately
    "raw_response": "TRANSCRIPT: …\nSCORE: 3\nFEEDBACK: …\nCONFIDENCE: 82",  // ≤ 20000
    "review_reason": null            // ≤ 500
  }]
}
```

Checks, in order:

1. Owner (404).
2. A lazy expiry check for this submission.
3. The token equals the stored one, else 409 (superseded or expired).
4. Already posted with this token: return the current payload with **200** and change nothing.
5. The run is active and not past its lease (409).
6. Unknown or duplicate box ids: 400.
7. A missing eligible box: 400 with `missing_box_ids`.
8. `scored` needs `0 <= score <= points`, else 400. The server never clamps.
9. `fallback_box_ids` must be eligible boxes (400). Results and fallback ids for protected boxes are ignored.

Rows written (`max_score = box.points`, `provider = "on_device"`, `raw_response` = the phone's reply):

| Box | Row |
| --- | --- |
| Protected | untouched |
| Server's own `blocked_reason` (recomputed) | needs review with that reason, no mark |
| Flagged, fallback available (`use_fallback` and `SELF_HOSTED_LLM_URL` set) | pending: no mark, not needs review, `review_reason = "Awaiting server re-mark"` |
| Flagged, fallback unavailable | needs review, `review_reason = "Fallback unavailable"`, no mark, phone's feedback kept |
| `blank` | `0`, "Nothing was written in this answer box." |
| `scored` | as posted |
| `needs_review` | needs review, the phone's reason or "The phone could not mark this answer" |

After saving:

- **No pending boxes:** `graded`, `graded_at`, and the teacher is notified.
- **Pending boxes:** the paper stays `grading`, and a background task:
  - rebuilds items with `build_grading_items` from the **server's** crops, keeping only the pending, unprotected boxes;
  - runs `grade_one(get_provider("self_hosted"), item)` four at a time;
  - writes `provider = "self_hosted"`, then sets `graded`, `graded_at` and notifies the teacher;
  - discards its work if the run was superseded, reset or expired meanwhile;
  - sends a box whose call failed to review.

The response is the my-grades payload plus `fallback` (`none` / `scheduled` / `unavailable` / `completed`) and `fallback_message`. It is 201 on the first save and 200 on a repeat.

Notification: kind `graded_on_device`, title `"<student>: <paper title> was marked on the phone"`, body `"<earned> of <max>[, <n> need review]"`, link `/submissions/{id}`.

When the run completes, `on_device_started_at` is cleared, while the token and `on_device_posted_at` are kept so a repeat post is recognised.

### 4.4 My grades

`{submission_id, question_id, grading_status, grading_error, released, provisional (= !released), earned, max_score, graded_count, needs_review_count (from submission_totals), pending_fallback_count, run: {started_at, posted_at, lease_expires_at}, boxes: [{answer_box_id, label, order_index, max_score, score, feedback, provider, needs_manual_review, review_reason, pending_fallback}]}`.

Every box of the paper is listed; a box with no row has `score: null`. Marks are **provisional until released**. `GET /api/submissions/{id}/grades` and `StudentAssignment` stay release-only for students.

### 4.5 Re-evaluation

Body: `{answer_box_ids?: [str], message?: str (≤ 1000)}`.

- 409 unless `graded`; 400 for unknown box ids.
- Calls `notify(course teacher, kind="reevaluation_requested", title="<student> asks for re-evaluation: <paper>", body="Parts: <labels>\n<message>", link="/submissions/{id}")`.
- Returns `{submission_id, notified}`. No new table.

### 4.6 Lease and sweeper

A run is stuck when `grading_status == "grading"`, `on_device_started_at` is set, and it started more than `ON_DEVICE_LEASE_MINUTES` ago. Both kinds of stuck run are handled the same way: a phone that never posted, and a fallback lost to a restart.

- Status becomes `failed`, with `grading_error = "On-device grading didn't finish in time. Grade it on the website, or ask the student to reopen the app."`
- Pending boxes become needs review with "Server re-mark did not finish".
- The token and both times are cleared.

The check runs at startup and then every 60 s (`main.py` lifespan, `services.on_device.sweep_forever`). It also runs lazily in start, results and my grades, so correctness never depends on the loop. Under test the loop is off (`app.state.on_device_sweeper = False` in `conftest.py`), and tests call `expire_stale_runs` directly.

## 5. Files added or changed

All paths are under `backend/`.

| File | Change |
| ---- | ------ |
| `routers/on_device.py` | **new**: the six routes |
| `services/on_device.py` | **new**: run lifecycle, saving results, fallback task, expiry and sweeper |
| `alembic/versions/a9c4d2e81f37_on_device_runs.py` | **new**: the migration |
| `tests/test_on_device.py` | **new**: 35 tests |
| `models.py` | `Submission`: three nullable columns |
| `schemas.py` | appended: `PackMarkers`, `PackBox`, `AssignmentPack`, `OnDeviceRunStarted`, `OnDeviceBoxResult`, `OnDeviceResultsIn`, `OnDeviceRunInfo`, `OnDeviceBoxGrade`, `OnDeviceGradesOut`, `OnDeviceResultsOut`, `ReevaluationRequest` |
| `config.py` | `ON_DEVICE_LEASE_MINUTES` |
| `main.py` | registers `on_device.router`; adds a lifespan that starts and stops the sweeper |
| `tests/conftest.py` | one line: sweeper loop off under test |

Plus this file, `addition_branch_phone.md`, at the repo root. The frontend is not touched.

### 5.1 Not part of this branch

`git status` also shows `backend/.env.example` and `frontend/.env.example` as **deleted** in the working tree. No session on this branch deleted them (first noticed in Session 7) and they are not meant to go away. The branch owner restores them before committing (`git restore backend/.env.example frontend/.env.example`), so the merged diff has no deletions. If they show up as deleted in the pull request, that is a mistake: do not merge the deletion.

## 6. Settings and migrations

| Setting | Purpose | Default |
| ------- | ------- | ------- |
| `SELF_HOSTED_LLM_URL` | Existing. Needed for fallback re-marking. A GPU-backed, OpenAI-compatible server; the provider appends `/chat/completions` (§8.3). If unset, flagged boxes become "Fallback unavailable" (needs teacher review) instead. | unset |
| `ON_DEVICE_LEASE_MINUTES` | New. How long a phone grading run may take, fallback included, before it expires | 15 |

**Migrations:** `a9c4d2e81f37_on_device_runs` (down-revision `f8a2c31e76b4`, now the single head). It adds `submissions.on_device_run_token VARCHAR NULL`, `on_device_started_at TIMESTAMP NULL` and `on_device_posted_at TIMESTAMP NULL`, and changes no existing column. The container applies it automatically on start (`alembic upgrade head` in the Dockerfile).

## 7. How to test

```
cd backend
python -m pytest tests/test_on_device.py
python -m pytest
```

The suite needs a `webend_test` database on the compose Postgres (`localhost:5434`). PDF tests need poppler on `PATH`.

Manual flow, with `$T` = a student's Entra access token and `$B` = `http://localhost:8000/api`:

```
curl -H "Authorization: Bearer $T" $B/student/assignments/<qid>/pack
curl -H "Authorization: Bearer $T" -X POST $B/student/submissions/<sid>/on-device/start
curl -H "Authorization: Bearer $T" -H "Content-Type: application/json" -X POST \
     $B/student/submissions/<sid>/on-device/results \
     -d '{"run_token":"<token>","use_fallback":false,"fallback_box_ids":[],"results":[{"answer_box_id":"<box>","outcome":"scored","score":3,"feedback":"ok","raw_response":"SCORE: 3\nFEEDBACK: ok\nCONFIDENCE: 80"}]}'
curl -H "Authorization: Bearer $T" $B/student/submissions/<sid>/grades
curl -H "Authorization: Bearer $T" -H "Content-Type: application/json" -X POST \
     $B/student/submissions/<sid>/re-evaluation -d '{"message":"Please look at part b"}'
```

## 8. Deploy checklist (for the teammate)

Names below come from `deploy/azure.sh`: resource group `webend-rg` (`:19`), container app `webend` (`:39`), image `ghcr.io/undying2021dreams/script-checker-web-end` (`:43`). If you run the script with other `RG` / `APP_NAME` values, use yours in the `az` commands.

At the end, send the branch owner the five values in §8.8.

### 8.1 Review

- [ ] Review the diff against `main` (`git diff main...feature/on-device-grading`). Expect the files in §5 and nothing else. **No `.env.example` deletions** (§5.1).
- [ ] `cd backend && python -m pytest tests/test_on_device.py` → all pass. The full suite needs poppler for the PDF tests (the Dockerfile has it; on a Windows machine without poppler, 13 unrelated tests fail. Session 11: 197 passed, 13 failed, all poppler).
- [ ] `cd backend && alembic heads` prints one head, `a9c4d2e81f37`. If `main` gained a migration since `c69eea2`, there are two heads: set this migration's `down_revision` to main's head before deploying.

**Migration the branch adds:** one, `a9c4d2e81f37_on_device_runs` (`f8a2c31e76b4 -> a9c4d2e81f37`): three nullable columns on `submissions` (`on_device_run_token`, `on_device_started_at`, `on_device_posted_at`). Additive, no data change, no backfill.

### 8.2 Build the image and deploy

Pick one.

**A. Merge (normal).**

- [ ] Merge `feature/on-device-grading` into `main` and push. The push starts `.github/workflows/image.yml`, which builds and pushes `:latest` and `:<commit sha>`. (It ignores pushes that change only `*.md`; this merge changes code, so it runs.) **Wait for it to go green.** `deploy` refuses an image the registry does not have, but it can't tell an old `:latest` from a new one.

**B. Deploy the branch without merging.**

- [ ] GitHub → Actions → **Image** → **Run workflow**, branch `feature/on-device-grading` (the workflow has `workflow_dispatch`). Note: this **also moves `:latest`** to the branch build (`image.yml` always tags both).
- [ ] Deploy that exact build: `IMAGE=ghcr.io/undying2021dreams/script-checker-web-end:<branch commit sha> ./deploy/azure.sh deploy`.

Then, for either option:

- [ ] If the database was stopped to save credit: `./deploy/azure.sh start`.
- [ ] `./deploy/azure.sh deploy`. **Migrations run on container start:** the container runs `alembic upgrade head && exec uvicorn …` (`Dockerfile:113`).
  - UNVERIFIED: whether `az containerapp update --image …:latest` with an unchanged tag always pulls the new image. If the new routes are missing afterwards (§8.7), deploy the exact build: `IMAGE=ghcr.io/undying2021dreams/script-checker-web-end:<commit sha> ./deploy/azure.sh deploy`.

### 8.3 Env var: `SELF_HOSTED_LLM_URL` (server re-marking)

A **GPU-backed, OpenAI-compatible** server. The web end posts to `<SELF_HOSTED_LLM_URL>/chat/completions` with `"model": "default"` (`services/llm_provider.py`, `SelfHostedProvider`, 120 s per call), so give the base that path hangs off:

| Server | Value |
| --- | --- |
| The Kaggle notebook cell (serves `/chat/completions` at the root; `/v1/…` returns 404) | `https://<id>.ngrok-free.dev`, **no `/v1`** |
| vLLM, llama.cpp, LM Studio | `https://<host>/v1` (vLLM also needs `--served-model-name default`) |

Checked on 2026-09-26 against the Kaggle cell running Qwen/Qwen3-VL-8B-Instruct on 2 GPUs: `GET /health` → `{"status":"ok",…}`, about 11 tokens/s. The ngrok address changes on every notebook restart, so set the variable again each time:

```bash
SELF_HOSTED_LLM_URL=https://<id>.ngrok-free.dev ./deploy/azure.sh deploy
# or, without a redeploy:
az containerapp update -g webend-rg -n webend --set-env-vars SELF_HOSTED_LLM_URL=https://<id>.ngrok-free.dev
```

`deploy` leaves the variable alone when it is empty (`azure.sh:209-212`), so a plain redeploy keeps the last address. If it is unset or the model is down, nothing breaks: flagged boxes go to the teacher as needs review ("Fallback unavailable", or "Server re-mark did not finish" after the lease).

### 8.4 Env var: `ON_DEVICE_LEASE_MINUTES` (optional, default 15)

How long a phone grading run may take, server re-marking included, before the sweeper marks it `failed` and the teacher's **Grade** button works again. Gemma 4 E2B takes about 20 to 25 s a box on the test phone, so 15 is enough for a demo paper. Don't go below about 10. `azure.sh` doesn't set it; set it once and later `deploy` runs keep it:

```bash
az containerapp update -g webend-rg -n webend --set-env-vars ON_DEVICE_LEASE_MINUTES=15
```

### 8.5 Entra: Android redirect on **your** (the deployed) registration

The phone signs in against the deployed registration directly (client id `08409bfc-af77-447a-9389-3466a29ea9dd` in `deploy/azure.sh:46` and `image.yml`; confirm it in §8.8). Without an Android redirect, Microsoft refuses the phone's sign-in.

1. Azure portal → Microsoft Entra ID → App registrations → the deployed registration (Web-End) → **Authentication** → **Add a platform** → **Android**.
2. Package name: **`com.example.capstone`**.
3. Signature hash: **`C3ASDt+nHPY0SKMEXBWNCK5zUic=`**. This is the branch owner's debug keystore, which signs the demo build. It is a certificate fingerprint, not a secret. Enter it exactly like that, **not** url-encoded.
4. **Configure**. The portal shows `msauth://com.example.capstone/C3ASDt%2BnHPY0SKMEXBWNCK5zUic%3D`. Nothing else from its MSAL snippet is needed; the app builds its own config.
5. Leave the SPA redirect (`https://<fqdn>/`) as it is.
6. **Supported account types** must include personal Microsoft accounts if any student signs in with one ("Accounts in any organizational directory and personal Microsoft accounts", `signInAudience` `AzureADandPersonalMicrosoftAccount`, `requestedAccessTokenVersion` 2). The phone uses authority `common`, as the website does (`VITE_AZURE_TENANT_ID=common`).
7. **Expose an API** must still have scope `access_as_user` under Application ID URI `api://<client id>`. The phone requests exactly `api://<client id>/access_as_user`, the same string as `image.yml`'s `VITE_AZURE_API_SCOPE`. If you changed the Application ID URI to anything else, say so in §8.8: the phone needs a code change for that.
8. Registration changes take **a few minutes** to apply. A sign-in right after saving can still fail.

A signed release build would need a second Android redirect with the release keystore's hash; the demo doesn't need it.

### 8.6 `TEACHER_EMAILS`, the course and the join code

- [ ] **The branch owner's student account must NOT be in `TEACHER_EMAILS`.** A listed account becomes a teacher on sign-in (`security.py`, `get_current_user`), and a teacher can't be a student in their own course (`POST /api/courses/join` → 409 "You teach this course").
- [ ] Promotion is **one-way**: `security.py` never demotes. If the student account was ever listed and signed in to the deployed site, taking it out of `TEACHER_EMAILS` isn't enough. Its `users.role` must be set back to `student` in the database.
- [ ] Optional: add the branch owner's **teacher** email so they can run the teacher side too. `deploy` sets `TEACHER_EMAILS` only when it **creates** the app (`azure.sh` `cmd_deploy`), so on an existing app set it directly, and keep your own address in the list:

  ```bash
  az containerapp update -g webend-rg -n webend --set-env-vars "TEACHER_EMAILS=<your email>,<branch owner's teacher email>"
  ```

- [ ] Create (or pick) a course, add a finalized paper to it, and send the **join code** (6 characters) to the branch owner. The student joins with it from the phone.

### 8.7 Confirm the deployed server is up

- [ ] `./deploy/azure.sh status` prints `URL: https://<fqdn>`. That is the phone's `webend.deployedUrl`.
- [ ] `curl https://<fqdn>/health` → `{"status":"ok"}`. With `--min-replicas 0`, the first request after a quiet spell is a cold start; give it up to a minute.
- [ ] The migration ran: `az containerapp logs show -g webend-rg -n webend --tail 100` shows `Running upgrade f8a2c31e76b4 -> a9c4d2e81f37`, then uvicorn starting.
- [ ] The new routes are live: `https://<fqdn>/openapi.json` lists `/api/student/assignments/{question_id}/pack`. (UNVERIFIED that the deployed app serves `/openapi.json`; FastAPI does by default and `main.py` doesn't turn it off.)
- [ ] The website still works: sign in as a teacher, open a course.
- [ ] Settings in place: `az containerapp show -g webend-rg -n webend --query "properties.template.containers[0].env[].name"` lists `SELF_HOSTED_LLM_URL`, `TEACHER_EMAILS` (and `ON_DEVICE_LEASE_MINUTES` if set).
- [ ] **When the branch owner tests, the server and the database must be running** (`./deploy/azure.sh start` if the database was stopped), and the self-hosted model too, if server re-marking is to be tried.

### 8.8 Send back to the branch owner

1. The deployed web address (`https://<fqdn>`, from `./deploy/azure.sh status`).
2. The registration's **client id** (Application (client) ID; expected `08409bfc-af77-447a-9389-3466a29ea9dd`).
3. **`VITE_AZURE_API_SCOPE`** as deployed (expected `api://08409bfc-af77-447a-9389-3466a29ea9dd/access_as_user`, from `image.yml`).
4. **`AZURE_TENANT_ID`** as deployed (expected `common`, `azure.sh:47`).
5. The course **join code**.

### 8.9 Smoke test with the branch owner

Phone on any network, deployed build: sign in, join, download the pack, photograph and hand in, grade on the phone. Then the teacher's bell shows "… was marked on the phone", a refresh shows the marks with provider `on_device`, and a flagged box (or every box, with the app's debug switch "Force server re-mark") shows provider `self_hosted` once re-marking finishes.

## 9. Known risks

- The answer key is on students' phones before they answer (demo decision). The pack route's docstring says so.
- A modified app could post fake marks. Mitigations:
  - marks stay provisional until the teacher releases them;
  - the phone's `raw_response` is kept;
  - the server re-checks ranges, completeness and blocked boxes.
- The model's self-reported CONFIDENCE is a weak signal, so bad replies and unreadable answers always count as low confidence.
- The teacher page isn't live; the teacher relies on the bell (checked every 60 s) and refresh.
- Teacher-side **Grade** on the website overwrites phone marks.
- The phone grades its own crops while the teacher and fallback see the server's crops of the same photo.
- Fallback is in-process background work. A restart loses it; the lease sweeper then fails the run and sends its pending boxes to review.
- With scale to zero, the sweeper loop runs only while a replica is up; the lazy check in the routes covers the rest.
- **The printed box label likely counts as ink on photos** (found in the Session 7 end-to-end test; not changed here). `services/grading.py` `looks_blank` trims 4 % of each edge, which removes the dashed border, but the `☐ answer` label (`doc_renderer.py` `.ab-label`, 11 px bold, `#888`) sits inside the trimmed area. On a real phone photo of a blank box, the label alone was 219 of 618,340 pixels = 0.035 %, over `BLANK_INK_FRACTION` (0.02 %). That was measured on the **phone's** crop of the same bbox; the server's own crop was not measured (UNVERIFIED), but it covers the same region. So server fallback, and the teacher's **Grade**, may send blank boxes to the model, which then recites the model answer as the student's work (seen on the phone). `tests/test_grading.py::test_blank_detection` uses label-free images, so it does not catch this. The phone now leaves the label's region out of its own count; the web end is unchanged on purpose.
- **Box QR codes were not read from phone photos** (Session 7): every upload reported 0 of 2 codes read, with 4/4 corner markers and every box cut. Not investigated, by choice. Known: the phone uploads the camera's JPEG unchanged (page about 2,750 px wide in the photo), and `pyzbar` imports and runs in the backend's `.venv`. The codes are a check only; crops and marks did not depend on them.

## 10. What has been tested

Every route in §4 is covered by `tests/test_on_device.py` (35 tests; last run Session 11, all passed; no code changed since Session 3). On a real phone against the **local** web end: pack, pack images, start, results, my grades, reset and discard (Session 7, below); "Fallback unavailable" (Session 9); Gemma 4 E2B two-turn marks posted as `on_device`, 5/5 and 10/15 (Session 9c); real fallback through `SELF_HOSTED_LLM_URL` with "Force server re-mark", boxes back as `self_hosted` (reported by the branch owner, 2026-09-27). Tested **only by pytest so far**: re-evaluation, lease expiry and restart. Nothing has run on the deployed server yet; §8.9 is that test.

### 10.1 Session 7 end-to-end test, as it touched this branch

Local web end on this branch, `ON_DEVICE_LEASE_MINUTES=2`, no `SELF_HOSTED_LLM_URL`, one phone.

| Route or behaviour | Seen working |
| --- | --- |
| `GET /api/student/assignments/{id}/pack` and pack images | yes |
| Upload, hand-in (existing routes) | yes |
| `POST …/on-device/start`, `POST …/on-device/results` | yes, provider `on_device`, needs-review reasons stored |
| `GET …/grades` (my grades) | yes |
| Teacher **Reset marks**, then a new phone run from `ungraded` | yes |
| Teacher **Discard**, then a fresh submission | yes |
| Bell notifications, override + release, `POST …/re-evaluation`, lease expiry, "Fallback unavailable", real fallback | not tested |
