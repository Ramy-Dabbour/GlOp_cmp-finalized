# Cloud Batch failure investigation

Job: `matlab-glop-cmp-20261007-135934-b1f7cc`  
Project: `strange-reducer-509621-e8`; region: `us-central1`  
Investigated: October 24, 2026. Read-only cloud investigation; no job was submitted, changed, restarted, or deleted.

## Confirmed cause

**The launcher imposed a 72-hour timeout on the MATLAB runnable. Google Batch terminated MATLAB when that timeout expired.** This is established by the submitted job specification and the live Cloud Console logs, not merely inferred from the three-day runtime.

The actual submitted specification (`submitted-batch.json`) has:

- `matlab-entry-1.timeout = "259200s"` (72 hours).
- `taskSpec.maxRunDuration = "266700s"` (74 hours 5 minutes, including preparation/output-transfer allowance).
- `taskSpec.maxRetryCount = 0` (automatic retries disabled).
- Four tasks, four `e2-standard-8` VMs, eight MATLAB workers per task.

The submitted MATLAB runnable timeout came from the project's `max_run_seconds` setting and the launcher's `seconds` value. It is not a default three-day Google Cloud job limit. The shorter runnable timeout fired before the overall task duration limit.

At **October 10, 2026, 14:09:58.728 UTC / 17:09:58.728 Cairo**, the Batch agent logged for task 2, runnable 2 (zero-based runnable index, named `matlab-entry-1`):

> Task task/matlab-glop-cmp-20-f0015c1e-5410-406b0-group0-2/0/0 runnable 2 execution err: command failed with exitCode -1. As it timed out, we overwrite its exitCode to 50005

The immediately adjacent message says `runnable 2 wait error: signal: killed`. Task 0's agent-state log also explicitly records `matlab-entry-1` finishing with exit code `50005`. The final job response records all four tasks as failed. Individual timeout rows for tasks 1 and 3 were not separately captured; the evidence above establishes the job's timeout failure mechanism.

## Why the final job summary says exit code 1

After MATLAB was killed, the `alwaysRun` `preserve-outputs` runnable uploaded the MATLAB log and flushed partial completed-trial records. It then deliberately raised:

> RuntimeError: Partial live results recovered; MATLAB did not complete every assigned trial

This is visible at **14:10:26.293 UTC / 17:10:26.293 Cairo** for task 2. Its output-preservation runnable subsequently exited with code `1`. Thus the final generic task exit code `1` hides the earlier, more informative MATLAB timeout code `50005`.

The submitted preservation code checks for full completion before exporting the completed MAT shard and transfer marker. Partial trial records are not equivalent to a completed benchmark MAT/CSV export. With `maxRetryCount=0`, Batch did not retry the failed tasks.

## Job timeline

The archived Google Batch API response, retrieved by the launcher on October 11, records:

| Event | UTC | Cairo (UTC+03:00 on these dates) |
| --- | --- | --- |
| Created | October 7, 14:00:19.252713936 | October 7, 17:00:19.252713936 |
| RUNNING | October 7, 14:08:06.084975246 | October 7, 17:08:06.084975246 |
| FAILED | October 10, 14:10:26.595749207 | October 10, 17:10:26.595749207 |

Recorded `runDuration`: **259340.510773961 seconds = 3 days, 2 minutes, 20.510773961 seconds**. The runtime includes preparation/cleanup and different task start times, which explains its exceeding the exact 72-hour MATLAB cutoff.

## Partial results and logs

The archived Cloud Storage inventory from October 11 lists **13,700 objects** under this exact job's output prefix, including **13,687 compressed trial-history objects**, live summaries, and all four MATLAB log files. Object count is not completed-trial count: each history object can contain multiple records. No final `.mat`, `.csv`, or `_TRANSFER_COMPLETE` object appears in that archived output-prefix listing.

The live Console log captured today reports task 2 retained 5,752 of 19,440 assigned trials and marked its state `incomplete`. Task 1 was still reporting completed-trial progress immediately before termination (8,262 completed at 14:09:22.957 UTC). These observations show the cloud run had made progress; this investigation has not downloaded or validated all retained scientific records and has not merged them into the local run.

Output prefix: `gs://strange-reducer-509621-e8-matlab-glop-cmp/outputs/matlab-glop-cmp-20261007-135934-b1f7cc/`.

## Evidence and provenance

- [Live job logs](https://console.cloud.google.com/batch/jobsDetail/regions/us-central1/jobs/matlab-glop-cmp-20261007-135934-b1f7cc/logs?project=strange-reducer-509621-e8), read through the existing authenticated Chrome session on October 24.
- `console-log-excerpts.json`: visible log messages transcribed from the browser, with UTC and displayed Cairo timestamps; deliberately labeled excerpts, not a complete API log export.
- `job-archived-20261011.json`: exact copy of the launcher's terminal-state Google Batch API response from `C:/Users/Dell/Documents/matlab-cloud-toolkit/state/workflow-20261011T092942Z-665e0a6b/jobs/GlOp_cmp/matlab-glop-cmp-20261007-135934-b1f7cc/job.json`.
- `submitted-batch.json`: exact copy of the original generated submission specification from `C:/Users/Dell/Documents/matlab-cloud-toolkit/state/workflow-20261007T135013Z-797a81d4/matlab-glop-cmp-20261007-135934-b1f7cc-batch.json`.
- `output-inventory-archived-20261011.json`: job-specific entries filtered from the launcher's saved Cloud Storage listing `workflow-20261011T092942Z-665e0a6b/command-0008.stdout.txt`; JSON formatting/date representation normalized by PowerShell.

A fresh CLI API request could not authenticate because the local Google Cloud CLI session needs reauthentication. The already authenticated browser did provide the actual logs. No credentials were changed or copied. Browser navigation later became unresponsive after the decisive log messages had been read; this does not affect the captured timeout/secondary-failure evidence.
