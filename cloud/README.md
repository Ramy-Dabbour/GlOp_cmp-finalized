# Google Cloud Batch execution

The active desktop launcher submits **N tasks on N VMs**, with **one MATLAB process worker per vCPU**. It calculates N from remaining quota immediately before submission. Both taskCount and parallelism equal N; taskCountPerNode is one. No extra tasks are queued.

## Active launcher

The project root matlab-cloud.json selects trial_shards mode, automatic task count and parallelism, an e2-standard-8 VM, eight workers, 8,000 CPU milli, 30,000 MiB of memory, and a 100 GB balanced boot disk per task. The installed launcher is in C:\Users\Dell\Documents\matlab-cloud-toolkit. Reviewable sources, installer, and regression tests are in this project's cloud/launcher directory. Restart the desktop matlab-cloud terminal after installing an update so its Python process loads the new modules and configuration.

The launcher reads regional and project-wide CPU quotas, instance quota, balanced disk capacity, and external IP quota. It verifies that the VM has exactly the configured worker count in vCPUs. N is the smallest number of complete VMs permitted by the remaining quotas. Missing quota information, incompatible resources, or zero capacity stops submission with an explanation. This check does not reserve capacity: other usage and regional availability can change before scheduling.

The October 6 inspection found:

| Quota | Limit | In use | Additional eight-vCPU VMs permitted |
| --- | ---: | ---: | ---: |
| Project-wide vCPUs | 32 | 8 | 3 |
| Regional vCPUs | 200 | 8 | 24 |
| VM instances | 24 | 1 | 23 |
| Balanced disk capacity, GB | 500 | 100 | 4 |
| External IP addresses | 8 | 1 | 7 |

The resulting plan is **three tasks, three VMs, eight workers per task, 24 workers total**. The 24-instance quota alone does not permit 24 eight-vCPU VMs. Future launches recalculate N. E2 consumes the shared CPUS quota, as specified in Google's machine-series quota table. When the existing job releases its eight vCPUs, the same global quota can accommodate four VMs and 32 workers. [Compute Engine allocation quotas](https://docs.cloud.google.com/compute/resource-usage)

## Work assignment

Edit scientific sweep inputs in +fpf/benchmarkConfig.m. The current sweep has 77,760 independent trials. The global index decodes [trial, MZI solver, reference solver, FIR order, passband ratio, seed], with the trial index varying fastest. fpf.trialParameters preserves original trial numbers and random substreams.

Batch sets BATCH_TASK_INDEX and BATCH_TASK_COUNT. Task k processes MATLAB indices k+1:N:totalTests. The launcher supplies FPF_WORKERS_PER_TASK=8 and a unique FPF_OUTPUT_DIR. fpf.prepareBatchPool creates exactly eight process workers, with one computational thread per worker. It updates only the session's local cluster object, without saving user profile changes. It errors for a mismatched existing pool instead of silently using the old four-worker default. The coordinating MATLAB client also starts with -singleCompThread.

fpf.runSweep has one parfor over each task's entire assigned parameter vector. Each iteration runs both solver stages; solver-internal parallelism stays disabled. With N=3, each task owns 25,920 trials and distributes them across eight workers. Without Batch environment variables, main.m retains local full-sweep execution.

Each VM has eight MATLAB workers plus a coordinating client. The operating system schedules them across the vCPUs; this does not set processor affinity. Memory includes the client and all workers. Verify representative peak memory before reducing the configured allocation.

## Isolation and collection

Each task has a private boot-disk workspace under /work/shared/tasks/00000, /work/shared/tasks/00001, etc. Source preparation, MATLAB logs, and results stay separate. The disk binding retains the previous COS storage repair.

Each task uploads one results/trial_shard_%05d.mat and a unique transfer marker containing its identity, worker count, and shard SHA-256. Logs are stored under tasks/%05d/logs. Task zero preserves the exact run's source under workspace; the original source snapshot also remains under runs/JOB_ID/source.

The desktop collector waits for terminal job status, downloads immutable object generations, checks every marker and shard checksum, then invokes the preserved run's fpf.mergeBatchResults through the configured local MATLAB executable. It batches downloads sharing a destination directory, with at most four concurrent transfer commands, preserving task folders and checking every file independently. The merger rejects missing, duplicated, misassigned, or incompatible trials. Failed jobs retain partial files for diagnosis and do not produce a complete benchmark. The combined benchmark_results.mat and CSV are saved next to the download snapshot in an aggregate-* directory; the terminal prints its full path.

Existing submitted jobs retain their original task count and source. These changes apply to the next submission.

## Live progress and completed trials

Live reporting is enabled in matlab-cloud.json. MATLAB creates a complete record immediately after each independent operating-point/sample trial finishes. A separate background runnable publishes new records and statistics about every 15 seconds, including while other trials are still optimizing. Publishing may take longer during network failures; it retries, retains the local spool, and exposes errors in the publish-live-trials Batch logs. This uses the same VM and bucket as the task; it does not add MATLAB workers or change quota-based task allocation.

For each job, inspect `gs://BUCKET/outputs/JOB_ID/live/` in Cloud Storage:

| Object | Contents |
| --- | --- |
| `summary.json` | Whole-job completion count, percentage, outcome counts, active/stale workers, throughput, approximate remaining time, task states, and most recent completed trial. |
| `tasks/00000/latest.json` | Task progress, assigned count, timing, errors, and each worker's current global trial ID, solver stage, evaluation count and activity age. |
| `tasks/00000/latest_trial.json` | The most recent completed trial's full result; replaced as new trials finish. |
| `tasks/00000/trials/SHA256.jsonl.gz` | Permanent trial history, in immutable compressed batches of at most 100 records. Repeat for each task index. |

Each trial record includes its global index, `[FIR order, passband ratio, seed, reference solver, MZI solver, sample]`, start/completion timestamps, wall time, outcome, end-to-end error, both solver results and metrics, fitted coefficients/design, convergence/exit flags, and failure details. Failed and nonconverged trials are retained. These are completed independent trials; individual objective calls only update inexpensive activity counters. Complex arrays contain `real`, `imag`, and `size`; nonfinite values are JSON `null`. Solver callback handles in diagnostics are represented by their function names.

Workers update activity every five seconds during objective evaluation, and at stage changes. A worker with no update for 120 seconds is marked stale. Staleness indicates a need to inspect logs; a single unusually long objective call can also cause it. A fresh uploader timestamp alone does not prove that an optimizer is progressing, so the report separately exposes worker activity and the last completed trial. A completed trial need not have converged: completion percentage includes all outcomes, and successes/nonconvergence/failures are separate counts. Estimated remaining time is approximate because solver costs differ.

Restart the desktop matlab-cloud terminal after installing the launcher. At its prompt, type:

```text
progress "GlOp_cmp"
progress ACTUAL_JOB_ID
```

The first command selects the latest submitted job for this project. The command prints live completion statistics, the latest result, and active workers' trial/stage/evaluation counters. The console's existing background monitor also prints a compact progress line each poll. From a Google Cloud terminal, download/print the bucket summary with:

```text
gcloud storage cat gs://strange-reducer-509621-e8-matlab-glop-cmp/outputs/ACTUAL_JOB_ID/live/summary.json
```

Final collection synchronously drains any unpublished trial records before uploading the final MAT shard or transfer marker. Counts describe records already uploaded, so a count cannot precede its trial data. Content hashes, a local upload ledger, create-only writes, and a shared process lock preserve records across upload retries and uploader restarts. Concurrent whole-job summary writers use generation preconditions. Incomplete sweeps retain partial live records and logs and do not produce a successful transfer marker. Jobs already submitted without live reporting cannot acquire it through local edits; the next submission includes these changes.

The uploader follows Google's [background runnable behavior](https://docs.cloud.google.com/batch/docs/reference/rest/v1/projects.locations.jobs#Runnable) and [Cloud Storage upload preconditions](https://docs.cloud.google.com/storage/docs/json_api/v1/objects/insert). It authenticates through the VM's attached service account; no new credential file is required. The SDK's bundled Python uses the image's system CA certificate bundle explicitly, with certificate and hostname verification enabled. If a live report is missing, the terminal checks for and displays the latest uploader error from Batch logs.

## Alternate native template

batch-job.template.json illustrates three tasks, one task per eight-vCPU VM, and eight workers per task. Replace image, bucket, region, service account, and licensing placeholders before use. This static template does not calculate quotas or invoke the desktop collector; download its shards and call fpf.mergeBatchResults manually after success. The active launcher uses the existing prepared MATLAB image and uploads source separately, so rebuilding the image is unnecessary.

[Batch task schema](https://docs.cloud.google.com/batch/docs/reference/rest/v1/projects.locations.jobs#TaskGroup) defines task counts and packing. The [5,000 parallel-task limit](https://docs.cloud.google.com/batch/quotas) is independent of compute quota.

## Validation

Run cloud/launcher/test_launcher.py with Python. From MATLAB:

```matlab
results = runtests("tests/parallelSweepTest.m");
assert(all([results.Passed]));
```

Checks cover quota selection, task isolation, completion validation, original traversal order, shard coverage, reproducibility, failure statistics, merging, and an eight-worker single-threaded pool. See cloud/launcher/VALIDATION.md for validation evidence.

Live-report checks: run `cloud/test_live_reporter.py`, `cloud/launcher/test_launcher.py`, and MATLAB `runtests("tests/liveReportingTest.m")`. The bounded cloud fixture is `python cloud/launcher/validate_cloud.py live-smoke`; it uses one eight-vCPU VM, 16 synthetic trials and a 600-second MATLAB timeout. It checks that uploaded results exist while Batch still reports RUNNING, then verifies final transfer and merge. It requires Google Cloud sign-in and available quota.
