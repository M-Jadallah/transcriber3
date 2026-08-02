> **SUPERSEDED / HISTORICAL - DO NOT USE FOR DEPLOYMENT OR CURRENT ACCEPTANCE:** This audit preserves only the state and findings observed when it was written. Its commands, service/network counts, Compose filenames, line references, findings, and configuration claims are obsolete and must not be used as current instructions or evidence. Use canonical `docker-compose.yml`, [`APPLICATION_ARCHITECTURE_AND_DEPLOYMENT_EN.md`](APPLICATION_ARCHITECTURE_AND_DEPLOYMENT_EN.md), and [`REMEDIATION_EXECUTION_STATUS.md`](REMEDIATION_EXECUTION_STATUS.md). Every result below is historical and was not rerun for the current static-only edits.

# Application and Coolify Deployment Audit

**Audit date:** 2026-08-02  
**Reference:** `APPLICATION_ARCHITECTURE_AND_DEPLOYMENT_EN.md`  
**Release verdict:** **BLOCKED - do not deploy this directory to Coolify**

## Executive Summary

The checked-out directory is not the complete application described by the architecture guide. It is an integration bundle that explicitly states the original YouTube/Deepgram backend and frontend source is absent. The current directory cannot build or run as an application.

There are five immediate release blockers:

1. `docker-compose.yml` is invalid YAML.
2. Required backend and frontend application files are missing.
3. The integration process requires a missing `docker-compose.formatting.yml` and fails after partially modifying its target.
4. The alternative Coolify Compose file uses backend build contexts that are incompatible with both backend Dockerfiles.
5. The formatting migration is not connected to the original Alembic history.

The formatting subsystem also has serious isolation and resource-control weaknesses. OpenCode receives general Bash access, mounts every formatting job, and shares the default Docker network with unauthenticated Redis. The current configuration therefore does not provide the isolation claimed by the guide.

It is not possible to certify the complete application as error-free because the original API, authentication, transcription workers, scheduler, exports code, frontend application shell, and original migrations are not present.

## Scope and Method

Reviewed areas:

- Architecture and deployment guide.
- Both Docker Compose files.
- Backend and formatting Dockerfiles.
- Nginx production configuration.
- Formatting API, repository, Celery task, skill installer, runtime, and OpenCode control code.
- Alembic migration and integration scripts.
- All available frontend formatting components.
- Environment examples, verification scripts, checksums, and reports.
- All available automated tests.

Verification performed:

| Check | Result |
|---|---|
| Python compile check | Passed for available Python files |
| Unit tests | **Failed: 22 passed, 2 failed, 1 skipped** |
| Canonical Compose YAML parse | **Failed** at `docker-compose.yml:1` |
| Alternate Compose YAML parse | Current canonical Compose contains 16 services; parser result was from an earlier snapshot |
| Project Coolify verifier | Passed, but misses the confirmed blockers |
| Frontend build | **Failed:** `frontend/package.json` is missing |
| Docker Compose validation/build | Not runnable because Docker is unavailable on this host |
| PostgreSQL/Redis/Alembic integration | Not runnable with the incomplete source and unavailable services |
| OpenCode/ChatGPT end-to-end test | Not run because it requires a deployed runtime and account authentication |

The tests were run in an isolated temporary environment. The available host Python is 3.14, while the Docker images target Python 3.12.

## Critical Findings

### C-01: The repository is not a complete application

**Evidence**

- `FULL_SOURCE_NOTICE.md:9-15` identifies the directory as an integration bundle.
- `SOURCE_COMPLETENESS_NOTICE_AR.md:3-14` says the original source must be supplied separately.
- `backend/Dockerfile:62-65` requires `backend/app/main.py`, which is absent.
- `frontend/Dockerfile:14-35` requires a complete package and build script, but `frontend/package.json` is absent.
- Present frontend files import missing modules such as `src/api.ts` and `src/hooks/useFetch.ts`.

**Impact**

The API image, worker services, scheduler, migration service, and frontend image cannot build or start. The original transcription, authentication, exports, and security behavior cannot be audited.

**Solution**

Restore the original source archive identified by SHA-256 in `FULL_SOURCE_NOTICE.md`, produce a clean merged source tree, and audit that final tree. Coolify must point to the merged repository, not this integration bundle.

### C-02: The canonical Compose file is invalid YAML

**Evidence**

- `docker-compose.yml:1` contains an uncommented prose line: `FULL COOLIFY STACK ...`.
- A direct PyYAML parse fails before reaching `x-backend-common` at line 8.
- The architecture guide tells Coolify to select `/docker-compose.yml` at `APPLICATION_ARCHITECTURE_AND_DEPLOYMENT_EN.md:343-355`.

**Impact**

Coolify cannot parse the documented deployment file or discover its services and variables.

**Solution**

Prefix line 1 with `#`, then require `docker compose -f docker-compose.yml config` to pass in CI with a complete environment.

### C-03: The integration package is incomplete and can leave a partial merge

**Evidence**

- `scripts/apply_formatting_integration.py:513-518` copies `docker-compose.formatting.yml`.
- That file is absent, although it is listed in `SHA256SUMS.txt:26` and the integration documentation.
- The missing file is accessed after backend/frontend copying and patching at `scripts/apply_formatting_integration.py:481-511`.
- The integration script recursively copies the bundled backend over the target, including Dockerfiles, requirements, and Alembic configuration.
- Both integration tests fail at the missing file.

**Impact**

The documented merge and full-source build workflows fail after target files have already changed. Existing application configuration can also be overwritten unintentionally.

**Solution**

Restore the checksum-verified overlay or remove all overlay references in favor of one canonical Compose file. Validate every source asset before writing, copy only an explicit allowlist of new files, merge dependencies deliberately, and build in a temporary tree before atomically replacing the target.

### C-04: The alternative Coolify file cannot build backend images

**Evidence**

- `docker-compose.coolify.generated-secrets.yml:3-5`, `:239-245`, and `:289-295` use `context: ./backend`.
- `backend/Dockerfile:25-26,62` copies paths beginning with `backend/`.
- `backend/Dockerfile.formatting:22-23,60` also copies paths beginning with `backend/`.

**Impact**

Docker searches for nonexistent paths below `backend/backend/`, so API, migration, worker, scheduler, OpenCode, and formatting-worker image builds fail.

**Solution**

Use repository-root contexts consistently:

```yaml
build:
  context: .
  dockerfile: backend/Dockerfile
```

Use `backend/Dockerfile.formatting` similarly. Validate every build target, not just Compose syntax.

### C-05: The Alembic migration is not linked to the original history

**Evidence**

- `backend/alembic/versions/20260801_0100_add_formatting_subsystem.py:4-8` says the current head will replace a placeholder.
- The actual assignment is `down_revision = None` at line 16.
- `scripts/apply_formatting_integration.py:490-496` only replaces `down_revision = "REPLACE_WITH_CURRENT_HEAD"`.
- `tests/test_apply_integration.py:82-85` expects `down_revision = "base1"` after integration.

**Impact**

Merging into an application with existing migrations creates another base or multiple heads. `alembic upgrade head` can fail during deployment.

**Solution**

Restore the exact placeholder or generate the migration with the discovered head. Make integration fail unless exactly one replacement occurs. Verify `alembic heads` returns one head and test upgrade/downgrade against PostgreSQL.

## High-Severity Findings

### H-01: OpenCode isolation is bypassable

**Evidence**

- `backend/app/formatting/runtime.py:91-115` denies most tools but allows all Bash commands by default.
- Only a few textual command prefixes are denied at `runtime.py:97-107`; wrappers, absolute paths, Python, Node, and Git bypass these checks.
- `docker-compose.yml:291-295` mounts the complete jobs volume and persistent OpenCode credentials into the OpenCode container.
- No Docker networks are declared, so all services share the default network.
- Redis has no password or ACL at `docker-compose.yml:101-111`.

**Impact**

A prompt-injected transcript or problematic skill can read or modify other jobs, attempt to access OpenCode authentication data, connect directly to Redis, destroy queue state, or publish crafted messages. This contradicts `APPLICATION_ARCHITECTURE_AND_DEPLOYMENT_EN.md:276-284`.

**Solution**

Run each formatting attempt in a disposable sandbox mounting only that attempt. Disable general Bash or expose a narrow allowlist of reviewed tools. Separate OpenCode from database/broker networks, authenticate Redis, and enforce outbound network policy. Keep OAuth credentials in a control plane that is not mounted into job execution sandboxes.

### H-02: Output controls can be bypassed and are enforced too late

**Evidence**

- `backend/app/formatting/runtime.py:278-285` silently ignores symlinks, special entries, empty files, and disallowed extensions.
- File-count and byte limits apply only to accepted artifacts at `runtime.py:286-306`.
- Validation occurs only after OpenCode exits at `backend/app/formatting/tasks.py:119-130`.
- `tests/test_runtime_workspace.py:86-102` is named as a symlink rejection test but asserts that the symlink is ignored.
- DOCX validation has no internal member-count or decompressed-size limit at `runtime.py:229-249`.

**Impact**

A job can fill persistent storage with ignored files, create excessive processes/files during execution, or submit a DOCX decompression bomb while still producing a small valid `result.md` and being marked successful.

**Solution**

Reject every symlink, hardlink, special file, disallowed extension, and unexpected output entry. Apply quotas while execution is in progress. Add CPU, memory, PID, log, file-count, workspace-size, and DOCX expansion limits before copying validated output into immutable storage.

### H-03: Job persistence and Celery publication are not atomic

**Evidence**

- `backend/app/formatting/repository.py:142-194` commits the queued job.
- Input staging and Celery publication happen later at `backend/app/api/formatting.py:375-405`.
- The Celery task claims a job through separate reads and commits at `backend/app/formatting/tasks.py:64-86`.

**Impact**

A process crash can leave a permanently queued job with no broker message. Duplicate/redelivered tasks can race on the same workspace. Audit persistence can also fail after a paid task has already been queued.

**Solution**

Use a transactional outbox, atomic conditional job claims, idempotency keys, and a lease/generation token. Add reconciliation for stale queued/running jobs and tests for process crashes, redelivery, and worker loss.

### H-04: Optional formatting is a hard dependency of the core application

**Evidence**

- `docker-compose.yml:170-182` makes the API wait for healthy `opencode-runtime`.
- `docker-compose.yml:386-388` then makes the gateway wait for the API.
- Formatting is described as optional in the architecture guide.

**Impact**

OpenCode startup, OAuth-volume corruption, or version incompatibility can prevent the original transcription application from becoming available.

**Solution**

Remove the OpenCode health dependency from the API. Let formatting status/endpoints report temporary unavailability. Keep OpenCode as a dependency only for the formatting worker.

### H-05: Disabling the default skill cannot select a replacement

**Evidence**

- `backend/app/formatting/repository.py:126-139` clears `default_skill_id` and commits when disabling a skill.
- `backend/app/api/formatting.py:230-245` then checks whether that already-cleared ID still equals the disabled skill.

**Impact**

The replacement branch never runs. New formatting requests fail until an administrator manually selects another default skill.

**Solution**

Read `was_default` before changing the skill, then disable it and choose the next enabled skill in one database transaction.

### H-06: Reverse-proxy HTTPS information is overwritten

**Evidence**

- `frontend/Dockerfile:59-73` sets `X-Forwarded-Proto` to Nginx `$scheme`.
- Coolify normally terminates TLS before the gateway, so Nginx receives HTTP and forwards `http` even for an external HTTPS request.
- Uvicorn trusts forwarded headers from every address at `docker-compose.yml:169`.

**Impact**

Secure redirects, callback URLs, cookie/origin checks, and OAuth behavior may use the wrong scheme. Trusting all forwarded sources also increases spoofing risk if network exposure changes.

**Solution**

Preserve the trusted Coolify proxy scheme with a validated fallback, forward host/port explicitly, and restrict Uvicorn trusted proxy addresses to the gateway network.

### H-07: OAuth responses and provider paths are insufficiently validated

**Evidence**

- `backend/app/formatting/opencode_client.py:68-103` interpolates `provider_id` into URL paths without an allowlist or URL encoding.
- `finish_oauth` converts any nonempty response object to `True`, including `{"success": false}`.
- OpenCode error bodies are returned through API errors at `opencode_client.py:35-39`.
- `frontend/src/components/FormattingSettingsPanel.tsx:99-112,314-331` opens a server-provided URL and assumes a stable `method` contract.

**Impact**

Authentication can be falsely reported as successful, provider paths can be malformed, sensitive diagnostics can reach users, and unexpected URL schemes can be opened.

**Solution**

Validate providers against the discovered provider list and a strict identifier pattern, encode path segments, validate OAuth URLs and schemes, define Pydantic response models, parse explicit success fields, and return sanitized errors.

## Medium-Severity Findings

### M-01: Docker ignore rules are inactive

The files are named `dockerignore` and `backend/dockerignore`; Docker recognizes `.dockerignore`. Root build contexts can therefore upload `.env` files, archives, caches, and Git metadata to the builder.

**Solution:** create a root `.dockerignore` appropriate for all root-context builds.

### M-02: Verification and checksum reports provide false confidence

`scripts/verify_coolify_bundle.py:31-65` does not require the original entry points, missing overlay, valid build contexts, migration lineage, network isolation, or image builds. It passed during this audit while the application remained undeployable.

`COOLIFY_BUNDLE_VERIFICATION_REPORT.md:7-14` claims 25 passing tests and successful parsing of the now-missing overlay. The current result is 22 passed, 2 failed, and 1 skipped. `SHA256SUMS.txt` also references the missing overlay and has stale values for at least:

| File | Manifest SHA-256 | Actual SHA-256 |
|---|---|---|
| `backend/Dockerfile.formatting` | `e925b255...` | `5128544b...` |
| Formatting migration | `5a010912...` | `be1dea5c...` |

**Solution:** replace the verifier with CI that checks all required files and checksums, Compose config, every image build, Alembic single-head status, migrations, tests, and container smoke tests.

### M-03: Secrets are passed to more services than necessary

The shared backend environment at `docker-compose.yml:14-37` gives admin/session credentials to workers, scheduler, and migration. The API receives all five Deepgram keys at `docker-compose.yml:143-148`.

**Solution:** split environment blocks by role and pass each secret only to services that use it.

### M-04: One-shot and long-running service health behavior needs correction

`storage-init`, `formatting-storage-init`, and `migrate` intentionally exit but are not marked for exclusion from Coolify health accounting. Transcription workers and scheduler have no health checks. The OpenCode control process is an unsupervised background process whose logs go to `/tmp` at `docker-compose.yml:275-280`.

**Solution:** mark one-shot services with the Coolify-supported health-check exclusion, add meaningful worker/scheduler checks, and supervise both OpenCode processes so the container exits if either child fails.

### M-05: Resource and shutdown policies are incomplete

There are no CPU, memory, PID, persistent-workspace, or container-log limits. Formatting can run for two hours but no deliberate worker drain or `stop_grace_period` is configured.

**Solution:** set production resource limits, log rotation, workspace quotas, and graceful shutdown/drain behavior for paid or long-running work.

### M-06: Build reproducibility is weak

Python dependencies use broad ranges, `yt-dlp` has no upper bound, base images use mutable tags, and `frontend/Dockerfile:16-25` can select `pnpm@latest` or run an unlocked `npm install`.

**Solution:** commit lock/constraint files, pin the package manager, use reviewed image versions or digests, and upgrade `yt-dlp` deliberately through tested releases.

### M-07: Formatting backup guidance omits the results volume

`APPLICATION_ARCHITECTURE_AND_DEPLOYMENT_EN.md:252` omits `formatting-jobs-data` from the regular backup list even though it contains formatting inputs and outputs. Artifact records store absolute paths at `backend/app/formatting/repository.py:286-302`.

**Solution:** back up `formatting-jobs-data` consistently with PostgreSQL and store artifact paths relative to a configured storage root.

### M-08: Documented cancellation and source-state guarantees are absent

The schema supports `cancelled`, but no cancellation endpoint or cooperative task cancellation exists. `backend/app/api/formatting.py:350-356` checks for a transcript relation but does not explicitly require the source job's completed state. `source_job_id` has no foreign key in the migration.

**Solution:** enforce completed source state, add a compatible source foreign key where the original schema permits it, and implement an atomic cancellation flag checked by the worker.

### M-09: Skill upload and snapshot persistence have concurrency gaps

`backend/app/formatting/skills.py:98-100,154-189` uses deterministic archive, temporary, and version paths. Concurrent identical uploads can race. At runtime, the ZIP hash is checked, but the previously extracted tree copied at `backend/app/formatting/tasks.py:103-116` is not verified against the archive.

**Solution:** serialize installation by hash, use unique temporary paths plus database conflict handling, clean up failed installs, and extract from the verified archive or validate a per-file manifest for every run.

**Source remediation update (2026-08-02, runtime-unverified):** the worker now constrains the content-addressed archive beneath `skill_archives_root`, matches skill name/slug/SHA snapshots, reads and hashes the bounded archive immediately before use, centrally reapplies ZIP path/type/count/unpacked-size/`SKILL.md`/folder-name rules, and materializes only the selected skill from those verified bytes into the generation exchange. Runtime execution does not inspect `extracted_path`; that cache may be missing or corrupt, and a matching re-upload repairs it atomically from the verified ZIP.

### M-10: Frontend asynchronous actions can produce incorrect or confusing state

- `FormattingSettingsPanel.tsx:26-43,222-225` enables Save before settings load, allowing hard-coded defaults to overwrite stored settings.
- `FormattingDetail.tsx:24-27,43-46` has no rerun busy state or error handling and allows rerun while a job is already queued/running.
- The API retains attempts, but the UI only fetches the latest attempt and exposes no history.

**Solution:** initialize editable state only after a successful load, disable actions while loading/submitting, show mutation errors, enforce server-side idempotency/single-flight rules where required, and expose attempt history.

## Confirmed Positive Controls

- No service publishes host ports; only the gateway is intended for Coolify domain attachment.
- No Docker socket is mounted.
- PostgreSQL, Redis, application data, formatting data, jobs, and OpenCode data use separate named volumes.
- Application images run as UID/GID 10001.
- Formatting containers drop Linux capabilities and use `no-new-privileges`.
- Uploaded skill archives reject Zip Slip paths and symbolic links and enforce archive limits.
- Original transcript snapshots and skill archives are SHA-256 checked before formatting.
- Artifact downloads recheck hashes and constrain paths below the formatting jobs root.
- React renders output previews as text rather than raw HTML.
- OpenCode host ports 4096 and 4097 are not publicly published.

These controls are useful but do not compensate for the release blockers and isolation gaps above.

## Required Remediation Order

1. Obtain and verify the complete original source archive.
2. Repair the integration package and perform the merge in a clean temporary tree.
3. Correct migration lineage and prove a single Alembic head.
4. Select one canonical Compose file and fix its syntax/build contexts.
5. Restore complete frontend/backend package files and lockfiles.
6. Isolate OpenCode, authenticate Redis, and remove general Bash capability.
7. Enforce runtime quotas and strict rejection of all unexpected outputs.
8. Fix job atomicity, skill-state handling, OAuth validation, and proxy headers.
9. Add role-specific secrets, health behavior, graceful shutdown, and backups.
10. Run the full release acceptance suite below before Coolify deployment.

## Release Acceptance Gate

All of the following must pass on the final merged repository:

```text
docker compose -f docker-compose.yml config
docker compose -f docker-compose.yml build --no-cache
python -m pytest
python -m compileall -q backend/app scripts tests
alembic heads                         # exactly one head
alembic upgrade head                  # against disposable PostgreSQL
npm ci
npm run typecheck
npm run build
```

Container-level acceptance must additionally verify:

- PostgreSQL and authenticated Redis health.
- Successful one-shot storage initialization and migration.
- API `/api/health` and gateway `/healthz` through the Coolify domain.
- Administrator authentication, session expiry, CSRF, and artifact downloads.
- A short YouTube transcription through each configured worker path.
- Worker loss, Celery redelivery, and stale-job reconciliation.
- Skill upload rejection cases and concurrent duplicate upload behavior.
- OpenCode cannot reach PostgreSQL/Redis or read another job workspace.
- A formatting run, rerun, cancellation, and account disconnect/reconnect.
- Rejection of symlinked, hardlinked, disallowed, oversized, excessive, and compressed-bomb output.
- Backup and restore of PostgreSQL, exports, skills, formatting jobs, and OpenCode authentication data.

## Final Assessment

The current directory is suitable only as a partially inconsistent integration artifact for further repair. It is not a deployable release and should not be connected to a public Coolify domain. A final error-free assessment requires the missing original source, repaired integration assets, successful image builds, database migration tests, and end-to-end container testing.
