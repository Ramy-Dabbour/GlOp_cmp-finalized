# Local benchmark execution and recovery

Run these commands from the project directory in PowerShell or Command Prompt:

```text
scripts\local-benchmark.cmd Install
scripts\local-benchmark.cmd Start
```

`Install` registers a Windows Task Scheduler task for the current signed-in user. It checks once per minute and at sign-in. It uses an interactive user token, stores no password, uses no cloud services, and opens a visible Windows Terminal (or PowerShell window) when recovery is needed. `Install` does not itself start MATLAB. `Start` opens the visible terminal; MATLAB executes `fpf.runLocalBenchmark` through `matlab -wait -batch` using the local Processes profile.

MATLAB emits progress throughout the run and saves it directly to `local-results/progress.log`. The terminal follows its attempt log and standard error every 200 ms. Each attempt has separate `matlab.log`, `stdout.log`, `stderr.log`, and `exit.json` files under `local-results/attempts`; the standard streams preserve failures that happen before MATLAB opens its own log. `supervisor.log` records starts, exits, and recovery decisions. `state.json` records benchmark progress; `supervisor.json` records recovery status. `active-attempt.json` records the worker PID and process creation time, allowing a replacement terminal to reconnect to a surviving worker. Exclusive file locks prevent duplicate supervisors.

Completed trials are committed by the MATLAB runner, including unsuccessful solver outcomes so the original benchmark statistics are preserved. Full trial results are stored in `local-results/checkpoints/trial_*.mat`. The project-root `benchmark_results.mat` and `benchmark_results.csv` are refreshed after each completed trial. Before completion, the summary is provisional; the MAT file includes a completed-trial mask and progress metadata, and solver pairs with no completed trials have `NaN` scores. Progress and solver activity are printed every 10 seconds during parallel execution and after each saved trial.

A replacement MATLAB process reloads committed results and calculates only unfinished trials. A terminal closing causes a new terminal to appear on the next scheduled check. A worker crash causes an automatic restart after 15 seconds, with repeated failures backing off to at most five minutes. A reboot or sign-out is recovered after the user signs in again; no code runs while the computer is off or asleep. Completion requires both MATLAB exit code zero and `state.json` status `completed`.

Intentional stop and resume:

```text
scripts\local-benchmark.cmd Stop
scripts\local-benchmark.cmd Resume
scripts\local-benchmark.cmd Status
```

`Stop` creates `local-results/STOP`, suppresses recovery, and asks MATLAB to exit at its next cancellation check. To terminate a stuck attempt immediately, use `scripts\local-benchmark.cmd Stop -ForceStop`; this validates the recorded PID and creation time before stopping its process tree. Trials not yet committed will be repeated. Closing the terminal or pressing Ctrl+C does **not** permanently stop recovery; use `Stop` for that.

To remove persistent recovery, use `scripts\local-benchmark.cmd Remove`. This also requests an intentional stop and keeps all results and logs. Add `-ForceStop` if immediate termination is needed.

The recovery task is named `GlOp_cmp Local Recovery <path hash>`. A computer restart requires an interactive sign-in before a visible terminal can be shown. Registration may require Windows permission to create a task; a failed registration is reported as an error and must be resolved before relying on reboot recovery.

## Isolated supervisor testing

The PowerShell script accepts `-OutputDirectory`, `-StateDirectory`, `-MatlabCommand`, `-TestWorkerScript`, `-RetrySeconds`, and `-MaximumRetrySeconds` for tests. `OutputDirectory` defaults to the project root and `StateDirectory` defaults to its `local-results` subdirectory. For MATLAB tests, set `-MatlabCommand` to an explicit fixture invocation and `-OutputDirectory` to the same output root that fixture uses. The default MATLAB command passes `OutputDirectory` directly to `fpf.runLocalBenchmark`. A lightweight test worker receives `-StatePath`, `-LogPath`, and `-StopPath`, writes progress to `LogPath`, and publishes JSON containing `status`, `completed_trials`, and `total_trials`. It can be killed via the PID in `active-attempt.json`, then the supervisor must relaunch it and preserve its committed count. `Install` refuses to register a lightweight test worker; a real MATLAB fixture can use an isolated output directory and distinct `TaskName`. Production MATLAB is not launched by the lightweight test harness.

Run the lightweight test with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\test-local-supervisor.ps1`. It forcibly kills one worker, verifies automatic restart, kills its supervisor, verifies reconnection to the surviving worker, checks duplicate suppression, checks exactly one commit for every fixture trial, and verifies that STOP prevents a watchdog launch. Test evidence is saved in a fresh `tests/results/supervisor-<id>` directory.

If MATLAB reports incompatible or corrupt checkpoints, automatic retries pause with `supervisor.json` status `needs_attention`. Repair the reported cause before calling `Resume`; saved trials are never deleted to resolve such an error.
