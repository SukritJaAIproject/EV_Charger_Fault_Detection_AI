# Desktop dataset inbox and monthly retraining boundary

## Scope

The Desktop app accepts a ZIP archive or a selected folder containing `.pcap`
and `.pcapng` files. It validates and stores captures as a monthly dataset
batch. Importing data never changes the active inference model.

The installed inference runtime remains NumPy-only. Candidate training runs in
an isolated external PyTorch environment configured on the workstation. The
Desktop package includes the deterministic worker code, while the CUDA/CPU
environment, source model definitions, and baseline `.pt` checkpoints remain
external dependencies. A missing training dependency disables only the Train
Model action; existing inference remains healthy.

The worker consumes an immutable snapshot of reviewed labels and capture
hashes. It writes a versioned candidate under the user's application-data
directory and never modifies the model bundled with the running application.

## Data flow

```text
ZIP or selected folder
        |
        v
Loopback dataset API (streaming upload)
        |
        +-- extension + PCAP magic validation
        +-- ZIP entry/path/link/size/ratio checks
        +-- SHA-256 deduplication
        v
%APPDATA%/<product>/training-datasets
        |
        +-- imports/<batch-id>/manifest.json
        +-- files/<sha-prefix>/<sha256>.pcap[ng]
        +-- labels/<sha-prefix>/<sha256>.json
        v
Ground-truth review -> Train Model candidate -> held-out gate -> manual approval -> release
```

Ground truth is assigned per capture content hash. A label therefore follows a
duplicate PCAP across monthly batches without creating conflicting copies.
Each label records `normal`, `fault`, or `exclude`; fault labels require one of
the eight supported fault families. Reviewer, notes, timestamps, revision and
the previous 100 revisions are retained for audit.

## Batch states

A batch is `uploading` while files arrive, `ready` once it is completed with at
least one capture, and `failed` when it cannot become ready:

- completing a batch that received no valid capture marks it `failed`
  (`failureReason` says why) and answers HTTP 422;
- a batch still `uploading` when the sidecar starts was interrupted (the app
  closed, or the upload stopped) and is marked `failed` at startup. Leftover
  upload temp files are deleted, and stored captures that no batch references
  any more are removed. That cleanup runs only when every batch manifest could
  be read: a manifest that is damaged, or held open by a scanner or backup
  tool, keeps every stored capture until it can be read again.

An unfinished batch (`uploading` or `failed`) can be discarded. Discarding
deletes the batch and every stored capture that only it referenced; captures
shared with another batch stay. Labels are kept, because they belong to the
capture content and come back if the capture is imported again. A `ready`
batch is reviewed ground truth and cannot be discarded from the app. The
Dataset tab offers "Finish with the files received" for an interrupted batch
that holds captures, and "Discard batch" for any unfinished one.

The Dataset tab stays mounted while other tabs are open, so switching tabs no
longer cancels an import in progress.

## API

Every route except `GET /health` requires the per-launch token (next section).
Errors are always a JSON body `{"detail": ...}` with the matching status.

- `GET /ai/fault-detection/datasets` — aggregate inbox state and every batch,
  newest first, plus `unreadableImports` (batches whose manifest cannot be read).
- `POST /ai/fault-detection/datasets/imports` — create a ZIP or folder batch.
- `POST /ai/fault-detection/datasets/imports/{id}/files` — stream one archive or capture.
- `POST /ai/fault-detection/datasets/imports/{id}/complete` — finalise a non-empty batch.
- `POST /ai/fault-detection/datasets/imports/{id}/discard` — delete an unfinished batch.
- `GET /ai/fault-detection/datasets/imports/{id}/labels` — list captures and current ground truth for a completed batch.
- `POST /ai/fault-detection/datasets/imports/{id}/labels` — create or revise one capture label using optimistic revision control.
- `GET /ai/fault-detection/training` — report training-engine readiness, eligible reviewed batches, and recent jobs.
- `POST /ai/fault-detection/training/preview` — count what a run on the selected
  batches would use, with captures shared between batches counted once, and
  whether it fits the 4 GiB run limit.
- `POST /ai/fault-detection/training/jobs` — snapshot selected batches and queue one isolated candidate run.
- `GET /ai/fault-detection/training/jobs/{id}` — report live stage, progress, failure details, and verified candidate metadata.

## Access control

The API listens only on a random loopback port and accepts the matching
embedded-web origin. Since 1.7.0 it also requires a per-launch secret: the
Electron launcher generates 32 random bytes at every start, passes them to the
sidecar in the `IMPS_API_TOKEN` environment variable (the sidecar removes it
from its environment so child processes never inherit it) and to the dashboard
in the launch URL. Every request except `GET /health` and CORS preflights must
send it in the `X-iMPS-Token` header; anything else gets HTTP 401. Another
local process, or another Windows account on a shared or RDP workstation, can
therefore find the port but cannot read datasets, change ground truth or start
training runs.

Local tooling (smoke tests, the PCAP check) reads the port and token from
`%APPDATA%/<product>/desktop-api.json`, which the launcher writes after the
sidecar is healthy and removes when the app closes. `%APPDATA%` is private to
the Windows account. A sidecar started without the variable fails closed: it
locks every route but `/health` with a random token nobody knows.
`smoke_runtime.ps1` passes its own token; `--no-api-token` serves the routes
openly and is meant for development only.

If the dataset or training store cannot be used (for example the folder was
moved behind a junction), the sidecar still starts: PCAP inference keeps
working, the dataset and training routes answer HTTP 503 with the reason, and
`/health` reports it under `retraining`.

Uploads are streamed to disk rather than held in memory.

## Storage and safety limits

- 4 GiB maximum HTTP upload; 512 MiB maximum individual capture.
- 20 GiB maximum expanded batch; 10,000 ZIP entries.
- The entry count and the central-directory size (at most 6 MiB) are read with
  zipfile's own end-record reader, which applies a ZIP64 record exactly as the
  parser will, before the archive is opened. A crafted directory of millions of
  records is refused without being parsed.
- Only stored and DEFLATE entries are read. BZIP2 and LZMA entries are rejected:
  Python bounds the output of a DEFLATE read but not of those decompressors, so
  a few kilobytes of BZIP2 could expand to gigabytes in one call.
- Every entry larger than 64 KiB must stay within a 200:1 compression ratio.
- Encrypted entries, links, drive-qualified names and parent traversal are
  rejected.
- A damaged entry (bad CRC, unreadable data) is rejected with a note and the
  rest of the archive is still imported; the batch manifest is written either way.
- Free disk space is checked before an upload and before extraction, keeping a
  512 MiB reserve; a full disk answers HTTP 507.
- Archive names are metadata only. Content is never extracted to an
  archive-controlled path.
- Captures are keyed by SHA-256, so duplicates do not consume another copy.
- Labels are keyed by the same content hash and written atomically. Stale edits
  receive HTTP 409 instead of overwriting a newer reviewer revision.
- A label file that cannot be read is reported (`invalidLabelCount`, and
  `labelInvalid` on the capture) and counts as unreviewed, so the batch cannot
  be trained until that capture is reviewed again. Saving the new label moves
  the unreadable file aside as `<sha256>.invalid-<timestamp>.json`.
- The Ground Truth tab starts every unlabelled capture with no decision and no
  fault family. Save stays disabled until the reviewer chooses Normal, Fault or
  Exclude, and a family for Fault.
- Each batch has its own lock, so a long ZIP import never blocks labelling or
  the dataset list; a folder import writes its manifest every 25 files or two
  seconds instead of after every file.
- Production models and the bundled benchmark are read-only during import and
  labeling.
- Only one training job can run at a time. The worker is launched without a
  shell, has an eight-hour limit, and is terminated when the Desktop sidecar
  exits.
- A training run is limited to 4 GiB of selected captures, and optimization
  windows are capped (20,000 LSTM-AE, 50,000 GRU) to bound CPU/GPU memory use.
- Decoded telemetry is written to the job's `work/` folder one capture at a
  time and deleted as soon as that capture is read; the folder itself is removed
  when the run ends and at startup.
- External baseline checkpoint hashes must reproduce the artifact version in
  the installed model manifest before training is enabled.
- Worker output is accepted only when both NumPy artifacts match the SHA-256
  values in the candidate manifest.

## Retraining gate

An imported batch is `ready` for label review, not ready for model promotion.
When every capture has a reviewed decision, it becomes selectable in Train
Model. The current safe fine-tune policy is:

1. `normal` captures provide optimization windows for LSTM-AE and GRU. The
   window caps are filled by a seeded uniform sample (reservoir sampling) over
   every window of every Normal session, with captures processed in content-hash
   order, so the sample covers the whole selection and does not depend on the
   order the batches were ticked. The result reports how many captures and
   sessions contributed windows next to how many were decoded;
2. `fault` captures are reserved and never used for gradient updates;
3. `exclude` captures are omitted;
4. each run starts from the audited baseline checkpoints with fixed seeds;
5. candidate `.npz` files and their manifest are stored under
   `%APPDATA%/<product>/model-training/jobs/<job-id>/candidate`;
6. every candidate remains `manual_validation_required` and cannot replace the
   production model from this tab.

Before promotion, a release process must still run the candidate on protected
held-out data, enforce regression thresholds for recall, false alarms and
latency, record approval, sign/package the manifest, and preserve rollback to
the previously shipped model. Fault captures shown as “reserved” in the Train
Model tab have not passed that evaluation merely because training completed.

## Training engine location

The worker runs under a separately installed Python with PyTorch, next to the
research project that defines the models and the baseline checkpoints. Each
location is taken from, in order: the sidecar command line
(`--training-python`, `--training-ai-project`, `--training-artifacts`), the
environment (`IMPS_TRAINING_PYTHON`, `IMPS_TRAINING_AI_PROJECT`,
`IMPS_TRAINING_ARTIFACTS`), the settings file
`%APPDATA%/<product>/model-training/engine.json`, and finally the research
workstation layout. The installed app passes no command-line paths, so on
another PC create `engine.json`:

```json
{
  "python": "C:\\Users\\me\\anaconda3\\envs\\ev_ai\\python.exe",
  "aiProject": "D:\\ev_charger_ai_v4_original_snapshot",
  "baselineArtifacts": "D:\\ev_charger_ai_data_v4\\artifacts"
}
```

The file is read on every status check, so a refresh in Train Model picks up an
edit without restarting. Train Model lists each requirement with its resolved
path, where it came from, and whether it is present.

`<product>` is the edition's product name, so each edition has its own
`engine.json`. The baseline checkpoints must reproduce the edition's installed
model artifact (the "Baseline checkpoints match the installed model"
requirement). The current line and the ISO 15118 edition ship the v4 weights
(`53b6f14244c2e633`), which the default `G:\ev_charger_ai_data_v4\artifacts`
matches. The Snapshot 2026-09-12 edition ships `41ded2cdd5c2ba3f`; point its
`%APPDATA%\iMPS Fault Detection Snapshot 2026-09-12\model-training\engine.json`
`baselineArtifacts` at the matching checkpoints (`G:\ev_charger_ai_data\artifacts`
on the research workstation). Both model sets have 33 input features, which the
worker checks before training.

## Forecaster windows (research item)

Inference calls the GRU forecaster only for delivery-phase events that carry an
EVSE voltage, while this fine-tune, like the baseline training script it
mirrors, builds forecaster windows from every V2G event of a session. The
recipe was kept for 1.7.0 so a candidate stays comparable with the shipped
baseline. Whether a delivery-only recipe calibrates the forecaster z-scores
better is an open research question; settle it on held-out data before any
candidate is promoted.

## Growth path

The current content-addressed local store is appropriate for one workstation
and monthly batches. Revisit storage when datasets exceed local disk capacity,
multiple reviewers need concurrent access, or centralized training is added.
At that point, keep the same manifest contract and move capture blobs to an
object store with server-side checksums and lifecycle retention.

The Desktop workflow deliberately labels a whole PCAP as the initial review
unit. If field captures contain multiple sessions with different outcomes,
promote the label key to `(sha256, session_id)` before training on those mixed
captures.
