function benchmarkResults = mergeBatchResults(shardDirectory,outputPath)
%MERGEBATCHRESULTS Validate all completed Batch shards, then write MAT/CSV.
%   Call only after the Batch job succeeds, using a directory for that run.
%   Missing/duplicate tasks or trials and mismatched sweep definitions fail
%   before any aggregate output is written.
    arguments
        shardDirectory (1,1) string
        outputPath (1,1) string = fullfile(shardDirectory,"benchmark_results.mat")
    end
    files = dir(fullfile(shardDirectory,"trial_shard_*.mat"));
    if isempty(files)
        error("fpf:IncompleteSweep","No Batch result shards were found.");
    end
    first = load(fullfile(files(1).folder,files(1).name),"trialResults");
    first = validateShard(first);
    config = first.config;
    totalTests = prod(fpf.sweepSize(config));
    taskCount = first.taskCount;
    fpf.batchWorkIndices(totalTests,first.taskIndex,taskCount);
    if numel(files) ~= taskCount
        error("fpf:IncompleteSweep",...
            "Expected %d Batch shards; found %d.",taskCount,numel(files));
    end
    merged = struct("config",config,"workIndices",(1:totalTests).',...
        "success",false(totalTests,1),"errors",zeros(totalTests,1),...
        "evaluations",zeros(totalTests,1));
    seenTasks = false(taskCount,1);
    seenTrials = false(totalTests,1);
    for fileIndex = 1:numel(files)
        loaded = load(fullfile(files(fileIndex).folder,files(fileIndex).name),...
            "trialResults");
        shard = validateShard(loaded);
        if ~isequaln(shard.config,config) || ~isequal(shard.taskCount,taskCount)
            error("fpf:InconsistentBatchResults",...
                "All shards must have the same configuration and task count.");
        end
        expectedIndices = fpf.batchWorkIndices(totalTests,shard.taskIndex,taskCount);
        if seenTasks(shard.taskIndex + 1) || ...
                ~isequal(shard.workIndices(:),expectedIndices) || ...
                numel(shard.success) ~= numel(expectedIndices) || ...
                numel(shard.errors) ~= numel(expectedIndices) || ...
                numel(shard.evaluations) ~= numel(expectedIndices) || ...
                any(seenTrials(expectedIndices))
            error("fpf:IncompleteSweep",...
                "A Batch shard has missing, duplicated, or incorrectly assigned trials.");
        end
        seenTasks(shard.taskIndex + 1) = true;
        seenTrials(expectedIndices) = true;
        merged.success(expectedIndices) = shard.success;
        merged.errors(expectedIndices) = shard.errors;
        merged.evaluations(expectedIndices) = shard.evaluations;
    end
    if ~all(seenTrials) || ~all(seenTasks)
        error("fpf:IncompleteSweep","The Batch shards do not cover the full sweep.");
    end
    benchmarkResults = fpf.summarizeSweep(merged);
    save(outputPath,"benchmarkResults","-v7","-nocompression");
    fpf.csv_export(outputPath);
end

function shard = validateShard(loaded)
    fields = ["config","workIndices","success","errors","evaluations",...
        "taskIndex","taskCount"];
    if ~isfield(loaded,"trialResults") || ...
            ~isstruct(loaded.trialResults) || ~isscalar(loaded.trialResults) || ...
            ~all(isfield(loaded.trialResults,fields))
        error("fpf:InvalidBatchShard","Invalid or missing trialResults in a Batch shard.");
    end
    shard = loaded.trialResults;
end
