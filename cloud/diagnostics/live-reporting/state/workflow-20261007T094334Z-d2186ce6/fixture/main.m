clear;

config = fpf.benchmarkConfig();
config.firOrders = 4;
config.passbandRatios = 0.2;
config.randomSeeds = 0;
config.referenceSolvers = 4;
config.mziSolvers = 4;
config.N_tr = 16;
config.N_s = 101;
maxTrialWorkers = 5000; % Pool ceiling; 0 selects serial local execution.
totalTests = prod(fpf.sweepSize(config));

batchTaskIndex = string(getenv("BATCH_TASK_INDEX"));
batchTaskCount = string(getenv("BATCH_TASK_COUNT"));
outputDirectory = string(getenv("FPF_OUTPUT_DIR"));
runAsBatchTask = false;
if batchTaskIndex ~= "" || batchTaskCount ~= ""
    taskIndex = str2double(batchTaskIndex);
    taskCount = str2double(batchTaskCount);
    workIndices = fpf.batchWorkIndices(totalTests,taskIndex,taskCount);
    % Retain full-sweep MAT/CSV output for the existing one-task launcher.
    % The native template explicitly sets FPF_OUTPUT_DIR, even for one task.
    runAsBatchTask = taskCount > 1 || outputDirectory ~= "";
end
if runAsBatchTask
    % Partition the global vector between VMs, then parallelize each shard
    % across one single-threaded process worker per allocated vCPU.
    if outputDirectory == ""
        error("fpf:MissingBatchOutputDirectory",...
            "Set FPF_OUTPUT_DIR to a persistent, run-specific Batch output directory.");
    end
    if ~isfolder(outputDirectory)
        mkdir(outputDirectory);
    end
    fprintf("Batch task %d of %d: %d of %d global trials.\n",...
        taskIndex + 1,taskCount,numel(workIndices),totalTests);
    liveDirectory = string(getenv("FPF_LIVE_DIR"));
    liveState = struct('schema_version',1,'status','initializing',...
        'started_at',fpf.TrialReporter.utcNow(),'task_index',taskIndex,...
        'task_count',taskCount,'assigned_trials',numel(workIndices),...
        'total_trials',totalTests,'config',config);
    if liveDirectory ~= ""
        mkdir(liveDirectory);
        fpf.writeLiveJson(fullfile(liveDirectory,'state.json'),liveState);
    end
    try
        batchWorkers = string(getenv("FPF_WORKERS_PER_TASK"));
        if batchWorkers == ""
            workerCount = 0; % Compatibility with the one-core native template.
        else
            workerCount = fpf.prepareBatchPool(str2double(batchWorkers));
        end
        if liveDirectory ~= ""
            liveState.status = 'running';
            liveState.workers_per_task = workerCount;
            fpf.writeLiveJson(fullfile(liveDirectory,'state.json'),liveState);
        end
        trialResults = fpf.runSweep(config,workIndices,workerCount,RunTrial=@liveSmokeTrial,LiveDirectory=liveDirectory);
        trialResults.taskIndex = taskIndex;
        trialResults.taskCount = taskCount;
        trialResults.workersPerTask = workerCount;
        outputPath = fullfile(outputDirectory,...
            sprintf("trial_shard_%05d.mat",taskIndex));
        save(outputPath,"trialResults","-v7","-nocompression");
        if liveDirectory ~= ""
            liveState.status = 'completed';
            liveState.finished_at = fpf.TrialReporter.utcNow();
            fpf.writeLiveJson(fullfile(liveDirectory,'state.json'),liveState);
        end
    catch exception
        if liveDirectory ~= ""
            liveState.status = 'failed';
            liveState.finished_at = fpf.TrialReporter.utcNow();
            liveState.failure_identifier = exception.identifier;
            liveState.failure_message = exception.message;
            fpf.writeLiveJson(fullfile(liveDirectory,'state.json'),liveState);
        end
        rethrow(exception);
    end
    fprintf("Saved %s. Merge shards after the Batch job completes.\n",outputPath);
    clearvars -except trialResults
else
    % A single parametric vector covers every operating point, solver pair,
    % and sample. runSweep contains the only parallel computational loop.
    workIndices = (1:totalTests).';
    trialResults = fpf.runSweep(config,workIndices,maxTrialWorkers);
    benchmarkResults = fpf.summarizeSweep(trialResults);
    benchmarkOutputPath = fullfile(fileparts(mfilename("fullpath")),...
        "benchmark_results.mat");
    save(benchmarkOutputPath,"benchmarkResults","-v7","-nocompression");
    fpf.csv_export(benchmarkOutputPath);
    clearvars -except benchmarkResults
end
