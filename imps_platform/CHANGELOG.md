## [1.7.0] 2026-10-06

First public release of the 1.3.5–1.7.0 work (fault pie chart, Dataset & Retrain,
Ground Truth Label, Train Model, Station Health), reviewed and fixed before release.

### Added

- Added a separate PCAP-derived Station Health score for all 212 stations without mixing in AI benchmark performance.
- Added health confidence, severity-weighted fault impact, connector-hotspot detection, score drivers, and a lowest-health sort in the Stations tab.
- Added a detailed health breakdown while keeping the existing Agentic AI benchmark score visible as a distinct metric.
- Added `engine.json` in the model-training folder to point Train Model at a PyTorch environment, research project and baseline checkpoints on any PC; Train Model now lists every requirement with its resolved path and where it came from.
- Added a training preview that counts the selected batches with shared captures counted once and checks the 4 GiB run limit before a run starts.
- Added Finish and Discard for import batches that were interrupted or received no valid capture.

### Security

- The loopback API now requires a per-launch token (`X-iMPS-Token`) on every route except `/health`. Another process or Windows account that finds the port can no longer read datasets, change ground truth or start training runs. A sidecar started without a token fails closed.
- ZIP imports read only stored and DEFLATE entries: a BZIP2 or LZMA entry of a few kilobytes could expand to gigabytes in one decompress call. The compression-ratio check now covers every entry above 64 KiB instead of only those above 1 MiB.
- The ZIP entry count and central-directory size (at most 6 MiB) are checked with zipfile's own end-record reader, ZIP64 records included, before the archive is parsed, so a crafted directory of millions of records is refused without using gigabytes of memory.

### Fixed

- Station Health weights ISOLATION_FAULT as a charger safety fault (it had the default protocol-error weight and could never be named as a driver), and a connector needs at least 20 sessions before it can be the station's hotspot (a single faulty session on a sparse connector cost 15 points).
- Ground Truth starts every capture with no decision: Normal was pre-selected (and PROTOCOL_FAILED for Fault), so one click per file could mark a whole batch Normal without review. Save stays disabled until the reviewer chooses.
- Train Model samples its capped training windows uniformly from every Normal session of the selection. The caps used to fill from the first few captures in click order, so later months had no effect while the counts claimed the whole selection was used. The result now reports the captures and sessions that contributed windows.
- A training run deletes its decoded telemetry (as large as the captures) as it goes and at the end; it used to stay in the roaming profile forever.
- A progress write that collides with the dashboard reading it no longer ends a multi-hour training run on Windows.
- An unreadable label file no longer breaks the Dataset, Ground Truth and Train Model tabs; the capture is shown as needing review again. Every API error now returns JSON instead of dropping the connection.
- A dataset or training store the app cannot use (for example behind a junction) disables only those tabs; PCAP analysis keeps working instead of the whole app failing to start.
- The dataset list shows every batch (it stopped at 24, which also hid batches from Ground Truth and Train Model).
- Switching tabs no longer aborts an import in progress, and an interrupted import is marked failed at the next start with its temp files and orphaned captures removed.
- A damaged ZIP entry is rejected without losing the rest of the archive, a full disk is reported before an upload starts, and a long ZIP import no longer blocks labelling.
- Removed the "automatic retraining" wording: retraining is always started by a person. Thai dates in the new tabs use the Gregorian calendar like the rest of the app, and the remaining English-only strings are translated.
- Removing captures that no batch references (after a crash or a discard) now happens only when every batch manifest was read; a damaged or locked manifest no longer costs its batch's reviewed captures.
- Completing a batch whose manifest cannot be written leaves it uploading so the request can be retried, and manifest writes retry briefly when Windows reports the file in use.
- PCAP analysis no longer fails at random when its progress file is being read for a status update at the moment the analysis writes it (Windows refuses the replace); progress writes retry and can never end an analysis.
- The desktop runtime's Python tests (now 63, including crafted-archive, recovery and concurrency tests) run in every `desktop:prepare` build.

### Editions

- Snapshot 2026-09-12 1.1.7 and ISO 15118 1.3.5 are built from this code. Where an edition's labels have no NO_POWER_DELIVERED family (the 2026-09-12 published labels of the Snapshot edition), the Stations tab and the station dialog say that PCAP Health cannot reflect power-delivery failures, and the fault chart caption mentions the data-split filter only in editions that have one.
- Train Model needs baseline checkpoints that reproduce the edition's own model: the Snapshot edition needs the `41ded2cdd5c2ba3f` checkpoints in its own `%APPDATA%\iMPS Fault Detection Snapshot 2026-09-12\model-training\engine.json`.

## [1.6.0] 2026-10-01

### Added

- Added a Desktop Train Model tab that selects fully reviewed dataset batches and runs real LSTM-AE/GRU fine-tuning with the workstation's PyTorch CUDA/CPU environment.
- Added live job progress, Normal/Fault/Exclude accounting, training-loss metrics, candidate artifact versions, and training history.
- Added isolated candidate storage and SHA-256 artifact verification; trained candidates require held-out validation and manual approval and never replace the production model automatically.

## [1.5.0] 2026-10-01

### Added

- Added a Desktop Ground Truth Label tab for reviewing every imported PCAP as Normal, Fault, or Exclude.
- Added the eight supported fault families, reviewer evidence notes, per-label revisions, and optimistic conflict protection.
- Added SHA-256 label reuse across duplicate captures, audit history, and live labeling progress for each dataset batch.

## [1.4.0] 2026-10-01

### Added

- Added a Desktop-only Dataset & Retrain tab for importing monthly PCAP datasets from a ZIP file or a selected folder.
- Added managed, content-addressed PCAP storage with SHA-256 deduplication, PCAP/PCAPNG validation, ZIP traversal protection, archive size limits, and import history.
- Added a monthly retraining readiness panel that keeps imported data staged until labels, held-out evaluation, and manual model approval are complete.

## [1.3.5] 2026-10-01

### Added

- Added a fault-distribution pie chart to the Stations tab, aggregating all 5,986 labelled fault sessions across all 212 stations.
- Added a responsive per-fault legend (fault family codes, with Thai and English headings). The fleet-wide chart remains unchanged when station search or data-split filters are applied.

## [1.0.0] 2024-02-20

### Original Release
