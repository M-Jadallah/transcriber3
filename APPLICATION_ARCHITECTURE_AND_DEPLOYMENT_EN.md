# Concise Architecture and Deployment Guide for the YouTube Transcription and AI Formatting Application

> This document summarizes the current application structure as reflected in the project files, Docker Compose configuration, and the added AI formatting subsystem.
>
> Static inspection shows a canonical 16-service Compose stack. This is the current source-level implementation state, not deployment certification: the complete original application source and required runtime verification remain unavailable, and no build or runtime execution is claimed here.

## 1. Application Purpose

The application converts YouTube videos or playlists into viewable and downloadable transcripts. It also allows the user to create a **new AI-formatted version** of any transcript without modifying the original text.

Primary goals:

1. Accept a YouTube video or playlist URL.
2. Download and normalize the audio.
3. Transcribe the audio with Deepgram.
4. Store the original transcript and export files.
5. Allow individual and bulk downloads.
6. Optionally run a formatting skill through OpenCode and a ChatGPT/Codex account to generate an independent derived version.

---

## 2. Core Technologies

| Component | Technology |
|---|---|
| Frontend | React + Vite + TypeScript |
| Web gateway | Nginx |
| API | FastAPI + Uvicorn |
| Database | PostgreSQL |
| Queue system | Celery + Redis |
| YouTube download | yt-dlp |
| Audio processing | FFmpeg |
| Transcription | Deepgram API |
| Database migrations | Alembic |
| AI formatting | OpenCode + ChatGPT/Codex |
| Deployment | Docker Compose on Coolify |

---

## 3. High-Level Architecture

```text
User
  │
  ▼
Gateway / Nginx
  ├── React Frontend
  └── /api/* ─────► FastAPI API
                         │
            ┌────────────┼─────────────┐
            ▼            ▼             ▼
       PostgreSQL      Redis       Persistent Storage
                         │
          ┌──────────────┴───────────────┐
          ▼                              ▼
Deepgram Workers 1..5            Formatting Worker
          │                              │
          ▼                              ▼
YouTube + FFmpeg + Deepgram       OpenCode Runtime
                                         │
                                         ▼
                                   ChatGPT / Codex
```

Only the `gateway` service should be exposed through the public domain. All other services remain internal.

---

## 4. Docker Services

The canonical Compose file defines 16 services; `worker-1..5` are grouped in one inventory row below.

| Service | Responsibility |
|---|---|
| `gateway` | Builds the frontend, runs Nginx, and proxies `/api` to the API service |
| `api` | Authentication, job management, transcripts, settings, skills, and downloads |
| `postgres` | Stores application data, jobs, and results |
| `redis` | Celery broker and queue state |
| `migrate` | Runs `alembic upgrade head` during deployment |
| `worker-1..5` | Downloads audio and performs transcription; each worker uses a Deepgram key |
| `scheduler` | Runs periodic maintenance tasks such as temporary-file cleanup |
| `formatting-worker` | Executes AI formatting tasks on a separate queue with default concurrency of one |
| `formatting-dispatcher` | Claims the persistent formatting outbox, performs recovery/reconciliation, and publishes jobs to Celery |
| `opencode-runtime` | Runs OpenCode and handles internal ChatGPT connection/disconnection flows |
| `storage-init` | Initializes permissions for audio, exports, and YouTube storage |
| `formatting-storage-init` | Initializes permissions and creates the fixed execution-exchange sentinel |

---

## 5. Original Transcription Flow

```text
YouTube URL
   ↓
Create job in PostgreSQL
   ↓
Send task to Redis/Celery
   ↓
Assign one of five workers
   ↓
yt-dlp: extract/download audio
   ↓
FFmpeg: MP3 Mono - 16 kHz - 64 kbps
   ↓
Deepgram: speech-to-text
   ↓
Validate result and reject empty transcripts
   ↓
Store TXT/JSON and export files
   ↓
Display and download from the web interface
```

Main characteristics:

- Supports multiple Deepgram keys for load distribution.
- Default practical concurrency is one task per worker.
- Retries transient failures.
- Honors `Retry-After` when available.
- Reuses existing files to avoid duplicate processing and cost.
- Deletes temporary audio after the configured retention period, defaulting to 24 hours.

---

## 6. AI Formatting Flow

Formatting produces a **derived artifact** and never replaces the original transcript.

```text
Completed original transcript
   ↓
Select skill + model + reasoning level
   ↓
Stage the immutable transcript snapshot
   ↓
Create a formatting job and formatting_outbox event in one transaction
   ↓
Formatting Dispatcher claims and publishes the event to Redis/Celery
   ↓
Copy transcript.txt into the generation-specific execution workspace
`/data/formatting-execution/<job-id>-g<generation>/`
   ↓
Materialize the validated selected skill into the generation exchange under .opencode/skills
   ↓
Persist transcript/title/config and per-skill-file hashes and sizes, then apply read-only input permissions
   ↓
Formatting Worker invokes OpenCode
   ↓
OpenCode uses ChatGPT/Codex
   ↓
Generate output/result.md and optional additional files
   ↓
Re-scan the exact input/skill/policy tree and reject any mutation before output handling
   ↓
Validate files and hashes
   ↓
Store the validated version at
`/data/formatting/jobs/<job-id>/executions/<job-id>-g<generation>/output/`
```

Job states:

```text
queued → running → completed
                 ↘ failed / cancelled
```

Each attempt stores an immutable snapshot of:

- Original transcript ID.
- Skill name, version, and SHA-256 hash.
- Selected model.
- Reasoning level: `low / medium / high / xhigh`.
- Original transcript hash.
- Attempt number.

This allows repeated formatting runs while preserving all previous results.

---

## 7. Skill Management

The web interface includes a dedicated page for uploading and managing skills.

Recommended ZIP structure:

```text
skill-name/
├── SKILL.md
├── scripts/
├── references/
└── templates/
```

Important rules:

- Exactly one `SKILL.md` must exist.
- Files must use UTF-8 encoding.
- The folder name must match the `name` value in the front matter.
- Unsafe paths, Zip Slip, and symbolic links are rejected.
- Every uploaded version is stored with a SHA-256 hash.
- Disabling a skill does not remove previous job results.
- Uploading a ZIP does not install dependencies or grant command execution. General Bash is denied, so skills are not documented as executing Python, Node.js, or image commands. A packaged `scripts/` directory remains read-only skill material, not an executable capability; image dependency changes apply only to reviewed application code unless a separate narrow execution design is approved.

---

## 8. ChatGPT and OpenCode Connection

Authentication is initiated from the application settings page. ChatGPT email addresses and passwords are not stored in environment variables.

Flow:

```text
Settings page
   ↓
API requests an OAuth start operation
   ↓
API calls the internal OpenCode service
   ↓
User completes authentication
   ↓
Tokens are stored in the persistent opencode-data volume
```

The interface provides:

- Connection status.
- Start connection.
- Authorization-code entry when required.
- Disconnect account.
- Default model selection.
- Reasoning-level selection.
- Default skill selection.

OpenCode ports `4096` and `4097` must remain internal and must not be exposed publicly.

---

## 9. Database Structure

The formatting subsystem adds the following tables:

| Table | Purpose |
|---|---|
| `formatting_skills` | Skill metadata, versions, and hashes |
| `formatting_settings` | Default model, reasoning level, and selected skill |
| `formatting_jobs` | Formatting attempts, status, and immutable snapshots |
| `formatting_outbox` | Durable dispatch, retry, recovery, and publication state |
| `formatting_artifacts` | Output files, sizes, types, and hashes |

The original transcription tables remain unchanged by the formatting feature.

---

## 10. Persistent Storage

| Volume | Contents | Mounted by |
|---|---|---|
| `postgres-data` | PostgreSQL database | `postgres` |
| `redis-data` | Persistent Redis data | `redis` |
| `audio-data` | Temporary audio files | `storage-init`, `api`, `worker-1..5`, `scheduler` |
| `exports-data` | Transcript and export files | `storage-init`, `api`, `worker-1..5`, `scheduler` |
| `youtube-config` | YouTube cookies and configuration | `storage-init`, `api`, `worker-1..5`, `scheduler` |
| `formatting-data` | Skill archives and extracted version cache | `formatting-storage-init`, `api`, `formatting-worker` |
| `formatting-jobs-data` | Input snapshots and generation-specific persistent results under `jobs/<job-id>/executions/<execution-key>/` | `formatting-storage-init`, `api`, `formatting-worker` |
| `formatting-execution-exchange` | Generation workspaces; the selected skill's runtime copy exists only here | `formatting-storage-init`, `formatting-worker`, `formatting-dispatcher`, `opencode-runtime` |
| `opencode-data` | Persistent OpenCode authentication data only; configuration and cache paths are tmpfs-backed | `formatting-storage-init`, `opencode-runtime` |

These are the canonical nine named volumes. `opencode-runtime` mounts only `opencode-data` at `/data/opencode/data` and the `formatting-execution-exchange` volume. It does not mount `formatting-data` or the persistent formatting-jobs volume. `formatting-dispatcher` mounts only the execution exchange for janitor work and receives no OpenCode configuration or authentication; the bounded DB-aware janitor preserves active/recent-lease and grace-aged generations. `XDG_CONFIG_HOME` and `XDG_CACHE_HOME` are under `/tmp`, which is tmpfs-backed. The storage initializer, not API configuration, creates the fixed sentinel in the hardcoded exchange path; worker and dispatcher exchange operations require that sentinel. The selected skill archive/version remains in `formatting-data`, but its selected runtime materialization is created only inside the generation exchange and is not copied into persistent jobs storage.

Back up `postgres-data`, `exports-data`, `formatting-data`, `formatting-jobs-data`, and `opencode-data` regularly.

---

## 11. Formatting Output Files

Allowed output extensions:

```text
.md  .txt  .docx  .json  .html  .pdf
```

Before a formatting job is marked successful, the system verifies:

- `output/result.md` exists and is not empty.
- No symbolic links are present.
- File-count and file-size limits are respected.
- The complete live execution workspace, including input, selected skill, output, configuration, and logs, remains within its entry and byte quotas and contains no links or special files.
- JSON files are valid.
- PDF headers are valid.
- DOCX files can be opened successfully.
- Every file has a SHA-256 hash, which is checked again during download.

---

## 12. Security and Isolation

- OpenCode does not receive `DATABASE_URL` or `REDIS_URL`.
- The Docker socket is not mounted into any container.
- OpenCode permissions are limited to the current job workspace and selected skill.
- General Bash execution and OpenCode web tools are blocked in the formatting workspace.
- Skill-provided scripts are not executable under this policy; per-job OpenCode OS mounts remain an explicitly blocked design item.
- OpenCode uses a separate internal control network and does not join the PostgreSQL/Redis network.
- `gateway` alone joins public/non-internal `edge`; it reaches the API over a separate internal `gateway` network. The API has no non-internal network and therefore no unrestricted egress path.
- `opencode-runtime` alone uses non-internal `formatting-egress`; transcription workers alone use non-internal `transcription-egress`. The formatting worker has neither egress network. `data`, `formatting-control`, and `gateway` are internal.
- PostgreSQL, Redis, session, admin, and OpenCode secrets are generated automatically by Coolify.
- Skill and settings management endpoints are protected by administrator authorization and CSRF controls.
- Uploaded skills must be treated as trusted code. Do not upload untrusted skill packages.
- The gateway has configurable static address `GATEWAY_PEER_IP` inside configurable `GATEWAY_NETWORK_SUBNET`; Compose derives API-only `FORWARDED_ALLOW_IPS` from the same value and Uvicorn trusts forwarded headers only from that address. The defaults are `172.29.0.2` and `172.29.0.0/24`, and the verifier compares both defaults directly and rejects an invalid subnet relationship. The backend image's standalone default disables proxy headers and never trusts `*`.
- Nginx replaces `X-Real-IP` and `X-Forwarded-For` with its immediate `$remote_addr`, strips incoming RFC `Forwarded`, rebuilds forwarded host from `$host`, and preserves incoming scheme only through an exact `http`/`https` map. Coolify is the trusted outer proxy and must sanitize client-supplied `Forwarded` and `X-Forwarded-*` headers, especially `X-Forwarded-Proto`, before routing only to the gateway.
- The gateway drops all capabilities before adding the stock-Nginx runtime minimum, uses a read-only root filesystem, and has tmpfs only for `/var/cache/nginx`, `/var/run`, and `/tmp`. Coolify IPAM/static-address support, proxy sanitization, collision-free host routing, and stock-image hardening compatibility remain mandatory staging runtime gates.
- The structural preflight enforces the canonical build matrix: every local build uses context `.`; backend roles use `backend/Dockerfile`; OpenCode and the formatting worker use `backend/Dockerfile.formatting`; and the gateway uses `frontend/Dockerfile`. It rejects image substitution for those roles and divergent images for the four image-only infrastructure roles. This does not execute Compose or build an image.
- The structural preflight applies a fail-closed runtime-override matrix to every service. It rejects privileged mode; noncanonical capability additions; host PID, IPC, UTS, user namespace, cgroup, runtime, and network modes; devices; host paths and bind mounts; environment/entrypoint overrides; host aliases and links; sysctls; and related host-escape controls. Only the two init services may specify root and `network_mode: none`, while the gateway retains only its exact stock-Nginx capability set. Canonical no-new-privileges, capability-drop, and read-only settings are exact where defined.
- Every top-level named volume must have an empty or null definition. Drivers, driver options, external/name/label metadata, scalar definitions, and host binding are rejected structurally.
- Frontend structural input gates require `index.html`, `package.json`, and at least one lockfile supported by the gateway Dockerfile. The unavailable original source does not establish exact Vite/TypeScript configuration filenames, so the preflight deliberately does not invent them and cannot prove transitive frontend completeness.

---

## 13. Repository Structure

```text
transcriber/
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── Dockerfile.formatting
│   ├── requirements.txt
│   ├── requirements-formatting.txt
│   ├── alembic.ini
│   ├── alembic/
│   └── app/
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   └── src/
└── docs/
```

---

## 14. Environment Variables

### Values entered by the user

```text
APP_ENV, APP_URL, APP_VERSION, TZ, LOG_LEVEL
ADMIN_USERNAME
SESSION_TTL_MINUTES, SESSION_IDLE_MINUTES
TRUSTED_HOSTS (production Compose fixes COOKIE_SECURE=true)
POSTGRES_DB, POSTGRES_USER
AUDIO_RETENTION_HOURS, AUDIO_BITRATE, AUDIO_SAMPLE_RATE, AUDIO_CHANNELS
DEFAULT_LANGUAGE, DEFAULT_DEEPGRAM_MODEL
DEEPGRAM_API_KEY_WORKER_1..5
OPENCODE_SERVER_USERNAME, OPENCODE_VERSION
FORMATTING_DEFAULT_MODEL, FORMATTING_DEFAULT_REASONING
FORMATTING_TIMEOUT_SECONDS, FORMATTING_INPUT_MAX_BYTES
FORMATTING_STORAGE_MAX_BYTES
FORMATTING_EXECUTION_WORKSPACE_MAX_ENTRIES, FORMATTING_EXECUTION_WORKSPACE_MAX_BYTES
FORMATTING_SKILL_MAX_*
FORMATTING_OUTPUT_MAX_*
```

### Secrets generated automatically by Coolify

```text
SERVICE_PASSWORD_64_POSTGRES
SERVICE_PASSWORD_64_REDIS
SERVICE_PASSWORD_64_ADMIN
SERVICE_HEX_128_SESSION
SERVICE_PASSWORD_64_OPENCODE
```

Do not manually define `DATABASE_URL`, `REDIS_URL`, `POSTGRES_PASSWORD`, `SESSION_SECRET`, or `OPENCODE_SERVER_PASSWORD` when the Compose file already derives them from the generated secrets.

Production Compose requires `APP_URL`, `TRUSTED_HOSTS`, and five dedicated Deepgram keys, fixes secure cookies, publishes no host ports, and exposes only gateway container port `80`. It is not a supported local stack as-is. Local operation requires a separate override with local ingress and dedicated manual secrets, including a local OpenCode password mapped to the same three roles; do not repurpose Coolify's generated-secret name as local guidance.

---

## 15. Deployment on Coolify

1. Push the complete repository to GitHub.
2. Create a Docker Compose resource in Coolify.
3. Select:

   ```text
   /docker-compose.yml
   ```

   Before Coolify deployment, an external release pipeline must successfully run actual Compose configuration validation and build every image. The Python preflight is not a substitute for either gate.

4. Let Coolify discover and generate environment variables.
5. Fill all empty values, including Deepgram keys.
6. Attach the public domain to the `gateway` service on internal port `80`.
7. Confirm that `GATEWAY_PEER_IP` is a usable address inside `GATEWAY_NETWORK_SUBNET`, does not overlap another host network, and that this Coolify version preserves the configured static address. Do not set `FORWARDED_ALLOW_IPS` separately.
8. Confirm the Coolify outer proxy overwrites client-supplied forwarding headers, supplies at most one exact `http` or `https` scheme, and cannot be bypassed. Also confirm the stock Nginx image starts with the configured read-only root, tmpfs mounts, and restricted capabilities. These staging checks are release gates because platform compatibility has not been run here.
9. Use **Rebuild without cache** for the first deployment.
10. Monitor services in this order:

   ```text
   postgres → redis → storage-init + formatting-storage-init → migrate
   → opencode-runtime → api → workers + scheduler
   → formatting-worker + formatting-dispatcher → gateway
   ```

The `migrate` service should finish successfully and then stop. This is expected behavior.

---

## 16. Post-Deployment Verification

- Open `/healthz` to verify Nginx.
- Check `/api/health` to verify the API.
- Sign in with the administrator account.
- Upload YouTube cookies when required.
- Test with a short video first.
- Confirm transcript display and downloads.
- Connect ChatGPT from the settings page.
- Upload a test skill.
- Run a formatting job and confirm that `result.md` is created.

---

## 17. Maintenance and Monitoring

- Monitor logs for `worker-1..5`, `scheduler`, `formatting-worker`, and `formatting-dispatcher`.
- Dispatcher health is functional freshness based on its atomic application heartbeat. Scheduler health only verifies that Tini has exactly one direct child and that its command line is `app.scheduler`; it is process liveness until the original scheduler exposes a functional heartbeat.
- Update `yt-dlp` periodically because YouTube changes frequently.
- Do not auto-update OpenCode in production. Change `OPENCODE_VERSION`, test, and rebuild deliberately.
- Monitor persistent-volume usage, especially audio and formatting outputs.
- Save generated secret values before moving the application to a new Coolify resource.
- Back up the database, skills, and output files regularly.

---

## 18. Project Summary

The intended merged application is a YouTube-to-text platform with an independent AI formatting subsystem. This integration-only workspace does not contain the complete original source and is not deployment-certified; actual Compose validation, all image builds, runtime tests, and Coolify staging remain mandatory.
