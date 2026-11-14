# GlOp_cmp checkpoint-preserving cloud replication

Production run identity: `matlab-glop-cmp-20261026-1405`.

The production plan is frozen in [plans/matlab-glop-cmp-20261026-1405](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/cloud/replication-20261026/plans/matlab-glop-cmp-20261026-1405). Its controller state and Batch API evidence are the authoritative launch/status records; this document does not imply that all 77,760 scientific trials are complete.

## Scientific and machine configuration

The replication retains all 77,760 trials, their global IDs and stage random streams, six solvers per stage, orders 4–12, passband ratios .2/.3/.4/.5, seeds 0/1/2, and 20 repetitions. The solver options, objectives, topology, feasibility tests and original positive-exit-flag scoring remain unchanged. New raw-result columns separately preserve observed error/evaluation counts for nonsuccess outcomes.

Sixty existing MATLAB functions are byte-identical to the active desktop source. The only modified existing function is the copied `TrialReporter.m`: advisory telemetry failures no longer abort scientific trials. New cloud execution and checkpoint helpers are confined to this snapshot. The root desktop source and live local benchmark were not changed.

The allocation retains four `e2-standard-8` VMs in `us-central1`, STANDARD provisioning, eight one-thread MATLAB Processes workers per VM, 8,000 CPU milli, 30,000 MiB task memory, 100 GB balanced boot disks, the original service account and both pinned container digests. The E2 allocation uses the shared regional CPU quota; four machines fit the checked 32-vCPU global quota after the smoke VM is released.

Source SHA-256: `32fccb2a1045390fc73044cbeab27fa128f8e195b7060a70009f833508349fa9`.
Scientific configuration SHA-256: `cf3ace5e4fd430fa3ea4b3a12f810e968cc3b5fcde61d2a80455d97e3bc7aa65`.

## Persistence and restart

1. Every completed trial, including nonconvergence and caught exceptions, writes its full result to an atomic immutable MAT checkpoint, followed by a JSON sidecar.
2. A separate publisher uploads the MAT and sidecar under content-addressed names, then creates an immutable per-trial commit marker. It writes a checksum-bound acknowledgment only after those objects are stored.
3. MATLAB counts the trial as durably completed after verifying that acknowledgment. It updates partial MAT and CSV exports after each acknowledged trial.
4. A restarted task verifies source/configuration identity, downloads and validates committed records, and submits only missing work. Content-addressed uncommitted uploads do not prevent safe reruns after a VM disappears halfway through an upload.
5. The publisher continually exports partial results, logs and worker activity. Foreground finalization also flushes remaining data when MATLAB exits unsuccessfully; it does not demand a complete sweep before preserving partial exports.

This protects committed completed trials from process/VM termination. It does not serialize the internal state of an optimizer in a still-running trial. Such a trial restarts from its assigned random stream if no committed result exists. Hard termination during the brief interval before a new result reaches Cloud Storage can lose that uncommitted result; the trial is then recomputed. The design never claims that unsaved RAM survives a hard VM failure.

There is no custom runnable timeout or task `maxRunDuration`. Batch retries failed tasks up to 10 times. Google independently imposes a 14-day RUNNING limit for these jobs; the recovery controller can submit a replacement job with the same source, configuration, task assignment and durable run namespace after a terminal failure. It waits for old VMs to disappear to prevent overlapping writers. Integrity/configuration mismatches require investigation instead of blind resubmission. See [Google's limits](https://docs.cloud.google.com/batch/quotas) and [task retry documentation](https://docs.cloud.google.com/batch/docs/automate-task-retries).

The local progress/recovery terminal polls cloud status about every 15 seconds and collects exports about every five minutes. Its Windows scheduled task, `GlOp_cmp Cloud Replication 20261026`, resumes at logon and has no execution time limit. Cloud tasks and their ten retries operate independently of the laptop. Cross-job rollover and local downloads require the monitor to be running; if the laptop is off, they resume at the next logon.

## Output locations

Durable cloud namespace: `gs://strange-reducer-509621-e8-matlab-glop-cmp/outputs/matlab-glop-cmp-20261026-1405/`.

- `checkpoints/tasks/NNNNN/trial_ID.commit.json`: authoritative per-trial commit.
- `checkpoints/tasks/NNNNN/objects/`: full MAT records and sidecars addressed by SHA-256.
- `artifacts/tasks/NNNNN/results/`: native MATLAB partial/final MAT tables and CSV exports.
- `artifacts/tasks/NNNNN/logs/`: MATLAB attempt logs.
- `live/summary.json`: aggregated durable counts and live worker activity.

Local downloads: [cloud-results/matlab-glop-cmp-20261026-1405](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/cloud-results/matlab-glop-cmp-20261026-1405).

`trial_results.csv` combines observed rows across shards and decodes each global ID into order, ratio, seed, solver pair and repetition. `benchmark_summary.csv` preserves the legacy score with the number of completed trials as its provisional denominator. `benchmark_results.mat` is a portable consolidated struct/array export. Original MATLAB table MAT files remain unchanged under `artifacts/tasks/`. Pending rows are explicitly incomplete and do not enter the provisional denominator. Partial-score comparisons remain scientifically provisional because the completed subset is not generally representative.

## Validation

- 10 MATLAB tests passed, including a real two-process pool, outcome retention, duplicate-free resume, interruption after three commits, invalid/mismatched receipts and a reporting failure after science returned.
- 18 uploader tests passed, including interruption at every remote upload cut point, a lost success response, immutable collisions, corrupted restore, and four-shard aggregation.
- 9 deployment/export tests passed, including recovery of a lost submit response, stable storage/configuration across replacement jobs, identity rejection, no blind resubmission after integrity failures, correct partial-score denominators, bounded local control-plane requests, and reading live status without referencing superseded object generations. Local request deadlines cannot impose a MATLAB computation timeout.
- Code Analyzer ran on cloud MATLAB helpers; remaining messages concern inherited `feature('getpid')` usage and one obsolete suppression, not parse errors.
- Separate real cloud recovery run: `matlab-glop-recovery-20261026-1355`, eight Processes workers, 24 synthetic trials, deliberate hard termination after three client-accepted commits, followed by Batch retry. Detailed verification is in [evidence/recovery-verification.json](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/cloud/replication-20261026/evidence/recovery-verification.json).

These execution tests validate scheduling, persistence and recovery. They do not constitute a real optimization benchmark or establish solver rankings. Scientific validity and limitations are assessed in the [peer-feedback response](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/review/peer-feedback-20261026/RESPONSE.md).

## Resume or inspect

Run the following from PowerShell to open the existing monitor in that terminal. The controller lock prevents a second monitor from submitting duplicate replacements:

```powershell
& 'C:\Users\Dell\Documents\MATLAB\GlOp_cmp\cloud\replication-20261026\Watch-Cloud-Replication.ps1' -Plan 'C:\Users\Dell\Documents\MATLAB\GlOp_cmp\cloud\replication-20261026\plans\matlab-glop-cmp-20261026-1405'
```

The manager's `status` and `collect` commands are read-only cloud operations. Its `submit` command submits a new Batch execution against the same frozen run namespace; do not call it while another execution of this run is active. `watch` handles that sequencing automatically. A `STOP_MONITOR` file in the plan directory stops only local monitoring, not cloud computation.
