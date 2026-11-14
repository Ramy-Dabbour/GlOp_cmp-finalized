# GlOp_cmp reliability fixes — verification report

**Recovery update, November 3, 2026:** Billing is enabled again. All **27,907 committed trials** from the October 28 run have been downloaded and verified, including full per-trial MATLAB results and combined MAT/CSV exports. The recovery snapshot is in `cloud-results/matlab-glop-cmp-20261028-fixes/recovery-backup-20261103`; its `verification.json` reports all checks passed. The prior job failed on October 31 when billing was disabled. Continuation job `matlab-glop-cmp-20261028-fixes-r01` was submitted November 3 at 11:02 UTC (13:02 Cairo), using the unchanged frozen source, scientific configuration, Batch configuration, and checkpoint namespace. At **14:00 Cairo**, all four tasks and **32 MATLAB workers** were running, all 27,907 checkpoints had been restored, and **29 new trials** were committed (**27,936 total; 49,824 remaining**). No upload errors or stale workers were reported. A newly saved MAT/JSON checkpoint was independently downloaded and validated. The failed job's idle VMs were released to resolve a CPU-quota conflict; its Batch record and GCS results remain preserved. Local monitoring and desktop computation remain disabled. See `recovery-20261103.md` and `recovery-completed-20261103.json` for evidence. The full experiment is still in progress.

**Operational update, October 29, 2026:** At the user's explicit request, the local cloud monitor and its terminal process tree were terminated. Both the cloud-monitor and desktop-recovery scheduled tasks are disabled, and the current cloud plan has a `STOP_MONITOR` marker. Do not restart local monitoring without a new user request. Cloud computation was not modified. Automatic local downloads and desktop-managed cross-job recovery are now off. See the plan's `monitor-disabled-by-user.json`. Monitoring status described below is historical verification from before this request.

**Historical verification, October 29:** The old cloud job `matlab-glop-cmp-20261026-1405` was CANCELLED and its VMs were gone. The replacement [matlab-glop-cmp-20261028-fixes](https://console.cloud.google.com/batch/jobsDetail/regions/us-central1/jobs/matlab-glop-cmp-20261028-fixes?project=strange-reducer-509621-e8) was submitted on October 28, 2026 at 23:32 Cairo time and was RUNNING. At the October 29, 17:59 Cairo verification, 9,131 of 77,760 trials were durably committed. Four cloud tasks each had eight MATLAB Processes workers; all four reported zero pending upload errors. The full sweep was still in progress.

This is a fresh dataset: no old desktop or cloud trial results were imported. Original results remain preserved. Completed outcomes, including nonconvergence and caught failures, are saved; temporary files, unfinished trials, and objects without commit markers do not count as completed.

## 1. Edit application

| Edit | Status |
|---|---|
| A1 | applied |
| A2 | applied |
| A3 | applied |
| A4 | skipped by switch |
| A5 | applied; approved one-line compatibility correction; all three tests pass |
| B1 | applied |
| B2 | applied |
| B3 | applied |
| B4a | applied |
| B4b | applied |
| B4c | applied |
| B5a | applied |
| B5b | applied |
| B5c | applied |
| B6a | applied |
| B6b | applied |
| B7a | applied |
| B7b | applied |
| B7c | applied |
| B8 | applied |
| B9 | applied |
| B10 | applied |
| B11a | applied |
| B11b | applied |
| B12 | applied |

Every selected FIND block matched exactly once before any source edit. Files retain LF endings and UTF-8 without BOM. A4 and its test were omitted by the supplied switch. Branch: `fpf-reliability-fixes`. No commit was made.

The user separately approved the two-line JSON export patch for the replacement cloud uploader. Its 21 isolated tests passed, and the patch is deployed. The old frozen source is unchanged.

## 2. Files changed

Counts compare against the pre-fix backups, excluding unrelated pre-existing repository changes.

| File | Added | Removed |
|---|---:|---:|
| `+fpf/TrialReporter.m` | 11 | 2 |
| `+fpf/writeLiveJson.m` | 8 | 1 |
| `+fpf/complexHarmonicExtrema.m` | 12 | 1 |
| `tests/telemetryRobustnessTest.m` | 78 | 0 |
| `C:/Users/Dell/Documents/analysis_pkg/fpf_analysis.py` | 42 | 20 |
| `C:/Users/Dell/Documents/analysis_pkg/README_analysis.md` | 4 | 3 |
| `C:/Users/Dell/Documents/analysis_pkg/analysis_plan.json` | 18 | 4 |
| New cloud snapshot: `cloud/durable_uploader.py`, compared with old snapshot | 2 | 2 |

Operational work separately added `STOP_MONITOR` to the old plan and stopped its controller, as explicitly requested. Reports, regression outputs, and replacement deployment preparation are separate artifacts. No original result data were edited. Detailed hashes and statuses are in `edit-application.json`.

## 3. A6 checks

> A6.1: The original October 7 launcher sets `FPF_LIVE_DIR`. The October 26 durable runner does not use that variable or execute `main.m`; it creates `results/live/<attempt>/trials` and passes the directory through `runCloudCheckpointTrial` to `runReportedTrial`. Per-trial diagnostic JSON is therefore written on the VM. The old uploader omitted trial JSON; the authorized replacement export patch includes it.

> A6.2: The only direct `roots(` / `eig(` calls in the root `+fpf` package are `chebyshevExtrema.m:7` and `complexHarmonicExtrema.m:28` after A3. No direct `eig(` call was found.

> A6.3: `TrialReporter.finish` still calls `fpf.writeLiveJson(path,record)` directly at line 59. That durable-record call is not made best-effort.

## 4. V2 and V3 results

MATLAB R2026a was executed through its terminal interface after the MATLAB connector returned `failed to attach to MATLAB session`.

Code Analyzer found no new messages in the three modified production files. Existing `feature('getpid')` advisories remain in `TrialReporter` and `writeLiveJson`. The new supplied test has the same advisory.

The initial `runtests('tests')` run executed 38 tests: 36 passed and 2 failed. All 35 existing tests passed, including actual Processes pools with 8 and 2 workers. Both new file-lock tests initially failed because their supplied helper used `fopen('all')`, which raises `MATLAB:fopen:FopenAllStagedRemoval` here. After explicit user approval, that one call was replaced with `openedFiles`; all three new tests then passed. No assertion or production code was weakened. All 35 existing tests and all 3 new tests have therefore passed across the full run and affected-test rerun. Evidence: `telemetry-retest.json` and `telemetry-retest.log`. MathWorks documents removal of the old option in R2025a and recommends [openedFiles](https://www.mathworks.com/help/matlab/ref/fopen.html).

Python before/after analyses were executed on both the current 5,182-trial dataset and an exact copied prefix containing IDs 1–4,947. Both modified runs produced **9 PASS, 0 FAIL, and one partial-coverage WARN**. The historical prefix matches every supplied spot value and all seven best-delta values. Both datasets produce 36×132 pair summaries, 65 added columns, 324 bootstrap rows, and 2,880 profile rows. Exactly the 11 prescribed timing columns changed among existing columns. All 9 exceptions are cost-incomplete: 5 telemetry failures and 4 eig failures. No expected numbers were adjusted.

Evidence: `matlab-validation.log`, `matlab-tests.json`, `checkcode.json`, `python-regression.json`, `out_before/`, `out_after/`, `out_before_4947/`, `out_after_4947/`, and `snapshot-provenance.json`.

All **10 cloud-checkpoint integration tests** passed on the assembled deployment snapshot before submission. These are local tests of the cloud runner using synthetic outcomes, including real process-pool scheduling, interruption after three committed trials, duplicate-free resume, invalid acknowledgments, and identity mismatch rejection. All **21 Python uploader tests** also passed, including JSON export, retry after JSON upload failure, and exclusion of temporary records from completion counts.

The deployment retains four `e2-standard-8` VMs, eight one-thread Processes workers per VM, the pinned MATLAB and transfer images, 100 GB boot disks, the original scientific configuration, and ten Batch task retries. No custom runnable timeout or task `maxRunDuration` is set. Source SHA-256: `813470dcc18ac0f022405b9ef2ad2a8b7261adfed5420e29c6076d5d03bb8d31`. Scientific configuration SHA-256 remains `cf3ace5e4fd430fa3ea4b3a12f810e968cc3b5fcde61d2a80455d97e3bc7aa65`.

Read-only cloud verification retrieved one committed MAT checkpoint and its per-trial JSON from each of the four tasks. All MAT and sidecar SHA-256 hashes matched their commit records; all MAT files were readable, retained the full result, and agreed with the JSON trial parameters and outcome. The remote source manifest and approved analysis plan exactly match the local frozen files. This is a four-trial integrity sample, not a checksum audit of every completed trial. Evidence: `remote-storage-verification.json` and `remote-checkpoint-samples/`.

The 17:54 Cairo local export contains 77,760 unique planned rows, of which 9,090 are marked complete and 68,670 pending. Its consolidated MAT and CSV agree exactly on IDs, completion masks, run identity, and all 36 solver-pair completed counts. The later 17:59 live count of 9,131 reflects subsequent cloud progress. Evidence: `final-output-verification.json` and `verified-live-summary.json`.

Output locations:

- Cloud results: `gs://strange-reducer-509621-e8-matlab-glop-cmp/outputs/matlab-glop-cmp-20261028-fixes/`
- Frozen source and analysis: `gs://strange-reducer-509621-e8-matlab-glop-cmp/runs/matlab-glop-cmp-20261028-fixes/`
- Local downloaded exports: `C:\Users\Dell\Documents\MATLAB\GlOp_cmp\cloud-results\matlab-glop-cmp-20261028-fixes\`
- Controller plan and log: `C:\Users\Dell\Documents\MATLAB\GlOp_cmp\cloud\replication-20261028\plans\matlab-glop-cmp-20261028-fixes\`

The old Windows recovery task is disabled. `GlOp_cmp Cloud Replication 20261028` is running and resumes at logon. The desktop benchmark remains stopped, with its STOP marker present and no MATLAB process active at verification. Local Google credentials expired during the overnight run; cloud computation continued, and monitoring/downloads resumed after the user reauthenticated. Current cloud execution and task retries do not depend on the desktop monitor. Local downloads and cross-job recovery require the device and valid local credentials.

A hash comparison of **10,419 original desktop data files** against the prior backup found no changes or missing files. The desktop STOP marker remains present. The 78,258,656-byte backup archive was uploaded to `gs://strange-reducer-509621-e8-matlab-glop-cmp/desktop-backup-20261028-5182/`; cloud MD5 `Z33YDt43vbnF786zHtbUKA==` matches the verified local archive. See `preserved-data-verification.json` and `desktop-backup-cloud-metadata.json`.

V4 human-only steps below were **not executed**. They are optional desktop verification steps, separate from the requested cloud restart.

First, if a fresh desktop run is desired:

```powershell
Rename-Item -LiteralPath 'C:\Users\Dell\Documents\MATLAB\GlOp_cmp\local-results' -NewName 'local-results-pre-fix'
```

Then run a few trials in a fresh output folder from MATLAB:

```matlab
cd('C:/Users/Dell/Documents/MATLAB/GlOp_cmp');
config=fpf.benchmarkConfig();
config.firOrders=4; config.passbandRatios=.2; config.randomSeeds=0;
config.referenceSolvers=4; config.mziSolvers=4; config.N_tr=3;
fpf.runLocalBenchmark(Config=config,RequestedWorkers=2, ...
    OutputDirectory=fullfile(pwd,'local-runs','post-fix-smoke'));
```

Analyze that fresh output and check that the telemetry-error filter returns no rows:

```powershell
& 'C:\Users\Dell\AppData\Local\Programs\Python\Python312\python.exe' -I 'C:\Users\Dell\Documents\analysis_pkg\fpf_analysis.py' 'C:\Users\Dell\Documents\MATLAB\GlOp_cmp\local-runs\post-fix-smoke\local-results\live' --out 'C:\Users\Dell\Documents\MATLAB\GlOp_cmp\local-runs\post-fix-smoke\analysis' --plan 'C:\Users\Dell\Documents\analysis_pkg\analysis_plan.json' --expect-trials 3
Import-Csv -LiteralPath 'C:\Users\Dell\Documents\MATLAB\GlOp_cmp\local-runs\post-fix-smoke\analysis\exceptions.csv' | Where-Object failureIdentifier -eq 'fpf:TelemetryWrite'
```

The user approved and fixed the delta ladder at −20 through −60 dB in 5 dB steps before the replacement launch, with every 10 dB used in the main-text table. `approved-decisions.json` records this decision and the plan SHA-256: `d51c49917e8ccd3cb4cd9d3d766b6e92eac7e281a286aa5d825134bf627f908d`. The approved analysis files and decision record were uploaded to the new run's separate `analysis/` folder before computation.

## 5. Residual risks

The supplied residual-risk statements are reproduced below. The actual execution status is recorded above.

- The eigenvalue failure site is not confirmed by a stack trace. A3 guards the most likely call. If `MATLAB:eig:NoConvergence` still appears in `exceptions.csv` after the next run, another call site exists.
- A `fpf:TelemetryWrite` error raised in `TrialReporter.finish` (the durable trial record) still ends the trial after 5 retries. This is deliberate.
- The new MATLAB tests and edits were not executed unless V2 was run. The lock-simulation tests rely on Windows sharing behavior of `fopen` and `movefile`.
- Stage-2 evaluation counts of a trial that failed before Stage 2 returned are not saved anywhere. The analysis flags these trials with `cost_incomplete` and uses wall-clock seconds, but evaluations stay undercounted.
- The delta ladder in `analysis_plan.json` is a proposal. It must be fixed by the human before the full-run tables are opened.

Additional observations:

- A3 changes the treatment of a numerical exception from trial termination to candidate rejection. The replacement requires a fresh source identity and dataset. Old prefixes will not be imported.
- Trial JSON is exported periodically. A hard VM loss before that export can leave JSON coverage behind committed full MAT checkpoints. Reconcile analysis coverage with commit IDs and recover missing records from MAT checkpoints before final analysis. Temporary files and uncommitted objects are not completed trials.
- If all five publication attempts fail, the supplied pauses sum to 0.75 seconds, excluding filesystem-call time; the attachment describes about 0.5 seconds.
- The supplied provenance text calls the ladder a priori while disclosing pilot-informed spacing. Describe it as fixed before the new full run and disclose the pilot influence.
- The half-band model and all four intended rho test cases remain unchanged. No architecture correction was applied.
- Live successful-trial counts and the legacy aggregate exports retain the original exit-flag scoring. The approved delta-based success criteria belong to the Python analysis layer; no final solver ranking is claimed from this incomplete run.

## 6. Exact backup files

- `C:\Users\Dell\Documents\MATLAB\GlOp_cmp\_pre_fix_backup\+fpf\TrialReporter.m`
- `C:\Users\Dell\Documents\MATLAB\GlOp_cmp\_pre_fix_backup\+fpf\writeLiveJson.m`
- `C:\Users\Dell\Documents\MATLAB\GlOp_cmp\_pre_fix_backup\+fpf\complexHarmonicExtrema.m`
- `C:\Users\Dell\Documents\MATLAB\GlOp_cmp\_pre_fix_backup\tests\telemetryRobustnessTest.m` (supplied test before the approved compatibility correction)
- `C:\Users\Dell\Documents\analysis_pkg\_pre_fix_backup\fpf_analysis.py`
- `C:\Users\Dell\Documents\analysis_pkg\_pre_fix_backup\README_analysis.md`
- `C:\Users\Dell\Documents\analysis_pkg\_pre_fix_backup\analysis_plan.json`
