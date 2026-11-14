# Verified recovery backup — November 3, 2026

All **27,907 committed trials** from the interrupted `matlab-glop-cmp-20261028-fixes` cloud run were retrieved and verified. See `verification.json`: `all_checks_passed` is true. The experiment contains 77,760 trials, leaving 49,853 at the recovery snapshot.

- `completed_trials.mat` and `completed_trials.csv`: combined exports of the 27,907 recovered trials.
- `checkpoints/tasks/`: original per-trial MAT files, JSON sidecars, and commit records. The MAT files retain full optimization results.
- `artifacts/`: 24 original exported MAT/CSV/log files, preserved as downloaded.
- `source-manifest.json`: identity of the frozen source/configuration.
- `remote-object-index.json`: inventory of 83,721 checkpoint objects.

Counts by shard are 7,590; 7,262; 7,021; and 6,034. The saved outcomes include 5,568 successes and 22,339 nonconvergences. Nonconverged trials are completed observations and remain part of the dataset.

Verification covered remote object sizes and MD5, MAT/JSON SHA-256 against commit records, experiment identity, unique IDs and shard assignments, frozen-grid parameters, MAT readability, and agreement between MAT and JSON outcomes. All checks passed after retrying transient download errors.

`verification-errors.json` and the earlier portion of `backup.log` document the first download pass's 57 transient failures. **All 57 were resolved by the retry.** They are retained as historical evidence; the final result is `verification.json` and `progress.json`, both successful.

Continuation job `matlab-glop-cmp-20261028-fixes-r01` was submitted on November 3 at 11:02 UTC using the unchanged frozen source and Batch configuration, and the same cloud checkpoint namespace. It resumes at committed trial boundaries; an interrupted, uncommitted trial starts again. The local backup is a fixed recovery snapshot, not a continuously updated mirror.
