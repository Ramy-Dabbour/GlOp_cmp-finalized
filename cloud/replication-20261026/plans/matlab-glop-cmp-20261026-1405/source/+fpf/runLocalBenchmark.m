function benchmarkResults = runLocalBenchmark(options)
%RUNLOCALBENCHMARK Resume a local sweep from durable individual trial results.
%   Each worker commits its full result before the client accepts it. The
%   client republishes MAT/CSV summaries after each accepted result. A crash
%   between those operations is repaired by scanning checkpoints on resume.
    arguments
        options.Config (1,1) struct = fpf.benchmarkConfig()
        options.RequestedWorkers (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(options.RequestedWorkers,-1)} = -1
        options.OutputDirectory (1,1) string = string(fileparts(fileparts(mfilename('fullpath'))))
        options.RunTrial (1,1) function_handle = @fpf.run
        options.HeartbeatSeconds (1,1) double {mustBePositive,mustBeFinite} = 10
    end
    outputDirectory = options.OutputDirectory;
    runDirectory = fullfile(outputDirectory,'local-results');
    checkpointDirectory = fullfile(runDirectory,'checkpoints');
    if ~isfolder(checkpointDirectory), mkdir(checkpointDirectory); end
    lockFile = java.io.RandomAccessFile(char(fullfile(runDirectory,'run.lock')),'rw');
    lockChannel = lockFile.getChannel();
    lock = lockChannel.tryLock();
    if isempty(lock)
        lockFile.close();
        error('fpf:LocalRunAlreadyActive','Another MATLAB process owns this local run.');
    end
    lockCleanup = onCleanup(@() releaseLock(lock,lockFile));
    config = options.Config;
    totalTests = prod(fpf.sweepSize(config));
    [parameters,pairIndices] = fpf.trialParameters(config,1:totalTests);
    try
        manifest = loadManifest(runDirectory,config,options.RunTrial,outputDirectory);
    catch exception
        state = struct('status','failed','failure_identifier',exception.identifier,...
            'failure_message',exception.message,'updated_at',fpf.TrialReporter.utcNow());
        fpf.writeLiveJson(fullfile(runDirectory,'state.json'),state);
        rethrow(exception);
    end
    trialResults = struct('config',config,'workIndices',(1:totalTests).',...
        'completed',false(totalTests,1),'success',false(totalTests,1),...
        'errors',zeros(totalTests,1),'evaluations',zeros(totalTests,1));
    progress = struct('schema_version',1,'status','initializing',...
        'manifest_id',manifest.id,'pid',feature('getpid'),...
        'started_at',fpf.TrialReporter.utcNow(),'updated_at',fpf.TrialReporter.utcNow(),...
        'completed_trials',0,'total_trials',totalTests,'successful_trials',0,...
        'failed_trials',0,'is_complete',false,'workers',0);
    futures = parallel.FevalFuture.empty;
    attemptDirectory = fullfile(runDirectory,'live',char(java.util.UUID.randomUUID()));
    mkdir(fullfile(attemptDirectory,'trials'));
    mkdir(fullfile(attemptDirectory,'workers'));
    progress.live_directory = char(attemptDirectory);
    attemptClock = tic;
    logPath = fullfile(runDirectory,'progress.log');
    try
        records = dir(fullfile(checkpointDirectory,'trial_*.mat'));
        for recordIndex = 1:numel(records)
            record = readCheckpoint(fullfile(records(recordIndex).folder,records(recordIndex).name),manifest,parameters);
            trialResults = acceptCheckpoint(trialResults,record);
        end
        progress.status = 'running';
        benchmarkResults = publishResults();
        report('RESUME: %d/%d committed trials; %d pending. Outputs: %s',...
            nnz(trialResults.completed),totalTests,nnz(~trialResults.completed),outputDirectory);
        pending = find(~trialResults.completed);
        if isfile(fullfile(runDirectory,'STOP'))
            progress.status = 'stopped';
            benchmarkResults = publishResults();
            report('STOP requested. All committed trials are preserved.');
            return
        end
        requestedWorkers = options.RequestedWorkers;
        if requestedWorkers == -1
            cluster = parcluster('Processes');
            requestedWorkers = cluster.NumWorkers;
        end
        workerCount = fpf.prepareTrialPool(min(requestedWorkers,numel(pending)));
        progress.workers = workerCount;
        if workerCount == 0
            for index = 1:numel(pending)
                if isfile(fullfile(runDirectory,'STOP')), break; end
                globalId = pending(index);
                report('START trial %d/%d',globalId,totalTests);
                record = fpf.runCheckpointTrial(options.RunTrial,parameters(globalId,:),...
                    config.N_s,attemptDirectory,globalId,checkpointDirectory,manifest.id);
                recordCompleted(record);
            end
        else
            pool = gcp('nocreate');
            nextIndex = 1;
            activeIds = zeros(workerCount,1);
            for slot = 1:min(workerCount,numel(pending))
                submitNext(slot);
            end
            lastHeartbeat = -Inf;
            while any(activeIds)
                if isfile(fullfile(runDirectory,'STOP'))
                    cancel(futures);
                    break
                end
                for slot = 1:numel(activeIds)
                    if activeIds(slot) == 0 || string(futures(slot).State) ~= "finished", continue; end
                    globalId = activeIds(slot);
                    if ~isempty(futures(slot).Error)
                        % A worker can commit successfully and then lose its
                        % connection. The committed MAT remains authoritative.
                        path = fullfile(checkpointDirectory,sprintf('trial_%012d.mat',globalId));
                        if isfile(path)
                            record = readCheckpoint(path,manifest,parameters);
                        else
                            throw(futures(slot).Error);
                        end
                    else
                        record = fetchOutputs(futures(slot));
                    end
                    recordCompleted(record);
                    activeIds(slot) = 0;
                    if nextIndex <= numel(pending), submitNext(slot); end
                end
                if toc(attemptClock)-lastHeartbeat >= options.HeartbeatSeconds
                    progress.updated_at = fpf.TrialReporter.utcNow();
                    fpf.writeLiveJson(fullfile(runDirectory,'state.json'),progress);
                    report('PROGRESS %d/%d (%.3f%%); successful=%d; other=%d; active=%s; elapsed=%.0fs',...
                        progress.completed_trials,totalTests,100*progress.completed_trials/totalTests,...
                        progress.successful_trials,progress.failed_trials,...
                        mat2str(activeIds(activeIds>0).'),toc(attemptClock));
                    reportWorkers(attemptDirectory,activeIds,@report);
                    lastHeartbeat = toc(attemptClock);
                end
                pause(0.25);
            end
        end
        if all(trialResults.completed)
            progress.status = 'completed';
        else
            progress.status = 'stopped';
        end
        benchmarkResults = publishResults();
        report('%s: %d/%d trials committed; MAT and CSV saved.',...
            upper(progress.status),progress.completed_trials,totalTests);
    catch exception
        if ~isempty(futures), cancel(futures); end
        progress.status = 'failed';
        progress.failure_identifier = exception.identifier;
        progress.failure_message = exception.message;
        progress.updated_at = fpf.TrialReporter.utcNow();
        fpf.writeLiveJson(fullfile(runDirectory,'state.json'),progress);
        report('ERROR %s: %s. Committed trials remain available for resume.',exception.identifier,exception.message);
        rethrow(exception);
    end

    function submitNext(slot)
        globalId = pending(nextIndex);
        nextIndex = nextIndex+1;
        activeIds(slot) = globalId;
        futures(slot) = parfeval(pool,@fpf.runCheckpointTrial,1,options.RunTrial,...
            parameters(globalId,:),config.N_s,attemptDirectory,globalId,checkpointDirectory,manifest.id);
        report('START trial %d/%d: FIR=%d passband=%.3g seed=%d solvers=%s/%s sample=%d',...
            globalId,totalTests,parameters(globalId,1),parameters(globalId,2),parameters(globalId,3),...
            config.solverNames(parameters(globalId,4)+1),config.solverNames(parameters(globalId,5)+1),...
            parameters(globalId,6));
    end

    function recordCompleted(record)
        trialResults = acceptCheckpoint(trialResults,record);
        benchmarkResults = publishResults();
        report('SAVED trial %d: success=%d error=%.9g evaluations=%g | %d/%d (%.3f%%); MAT+CSV committed',...
            record.globalId,record.success,record.error,record.evaluations,...
            progress.completed_trials,totalTests,100*progress.completed_trials/totalTests);
        if isfield(record.result,'failureMessage') && strlength(string(record.result.failureMessage))>0
            report('Trial %d outcome: %s',record.globalId,string(record.result.failureMessage));
        end
    end

    function summary = publishResults()
        summary = fpf.summarizeSweep(trialResults);
        completedPerPair = accumarray(pairIndices, double(trialResults.completed),[height(summary),1]);
        trialsPerPair = totalTests/height(summary);
        if ~all(trialResults.completed)
            hasCompleted = completedPerPair>0;
            summary.favorabilityIndex(hasCompleted) = summary.favorabilityIndex(hasCompleted) .* ...
                trialsPerPair ./ completedPerPair(hasCompleted);
            summary.favorabilityIndex(~hasCompleted) = NaN;
        end
        progress.completed_trials = nnz(trialResults.completed);
        progress.successful_trials = nnz(trialResults.success);
        progress.failed_trials = nnz(trialResults.completed & ~trialResults.success);
        progress.is_complete = all(trialResults.completed);
        progress.updated_at = fpf.TrialReporter.utcNow();
        writeSnapshots(outputDirectory,summary,trialResults,progress);
        fpf.writeLiveJson(fullfile(runDirectory,'state.json'),progress);
    end

    function report(format,varargin)
        line = sprintf('[%s] %s\n',fpf.TrialReporter.utcNow(),sprintf(format,varargin{:}));
        fprintf('%s',line);
        file = fopen(logPath,'a','n','UTF-8');
        if file<0, error('fpf:ProgressLogWrite','Cannot append %s.',logPath); end
        fileCleanup = onCleanup(@() fclose(file));
        fprintf(file,'%s',line);
    end
end

function manifest = loadManifest(runDirectory,config,runTrial,outputDirectory)
    path = fullfile(runDirectory,'manifest.mat');
    sourceHash = computeSourceHash();
    if isfile(path)
        try
            saved = load(path,'manifest');
            manifest = saved.manifest;
            valid = manifest.schemaVersion==1 && isequaln(manifest.config,config) && ...
                strcmp(manifest.sourceHash,sourceHash) && strcmp(manifest.runTrial,func2str(runTrial));
        catch
            error('fpf:CorruptCheckpoint','The checkpoint manifest is unreadable: %s',path);
        end
        if ~valid
            error('fpf:CheckpointMismatch',...
                'Configuration or MATLAB source changed. Existing results were preserved; use a new output directory for a different experiment.');
        end
    else
        records = dir(fullfile(runDirectory,'checkpoints','trial_*.mat'));
        if ~isempty(records)
            error('fpf:CorruptCheckpoint','Trial checkpoints exist without their manifest.');
        end
        backupDirectory = fullfile(runDirectory,'previous-outputs');
        for name = ["benchmark_results.mat","benchmark_results.csv"]
            original = fullfile(outputDirectory,name);
            if isfile(original)
                if ~isfolder(backupDirectory), mkdir(backupDirectory); end
                copyfile(original,fullfile(backupDirectory,name));
            end
        end
        manifest = struct('schemaVersion',1,'id',char(java.util.UUID.randomUUID()),...
            'config',config,'sourceHash',sourceHash,'runTrial',func2str(runTrial),...
            'createdAt',fpf.TrialReporter.utcNow());
        temporary = string(tempname(runDirectory))+'.mat';
        save(temporary,'manifest','-v7');
        fpf.atomicReplace(temporary,path);
    end
end

function value = computeSourceHash()
    directory = fileparts(mfilename('fullpath'));
    files = dir(fullfile(directory,'*.m'));
    [~,order] = sort({files.name});
    digest = java.security.MessageDigest.getInstance('SHA-256');
    for index = order
        digest.update(unicode2native(files(index).name,'UTF-8'));
        digest.update(unicode2native(fileread(fullfile(directory,files(index).name)),'UTF-8'));
    end
    value = lower(reshape(dec2hex(typecast(digest.digest(),'uint8'),2).',1,[]));
end

function record = readCheckpoint(path,manifest,parameters)
    try
        saved = load(path,'checkpoint');
        record = saved.checkpoint;
        id = record.globalId;
        [~,name] = fileparts(path);
        assert(isscalar(id) && isfinite(id) && id==fix(id) && id>=1 && id<=size(parameters,1));
        assert(strcmp(name,sprintf('trial_%012d',id)));
        assert(record.schemaVersion==1 && strcmp(record.manifestId,manifest.id));
        assert(isequal(record.parameters,parameters(id,:)));
        assert(islogical(record.success) && isscalar(record.success));
        assert(isnumeric(record.error) && isreal(record.error) && isscalar(record.error));
        assert(isnumeric(record.evaluations) && isreal(record.evaluations) && isscalar(record.evaluations));
        assert(isstruct(record.result) && isequal(logical(record.result.success),record.success));
        if record.success
            expectedError = fpf.endToEndError(record.result.rawSincReference,...
                record.result.mziResult.realizedCoefficientMatrix);
            expectedEvaluations = record.result.referenceResult.metrics.functionEvaluations + ...
                record.result.mziResult.metrics.functionEvaluations;
            assert(isequaln(record.error,expectedError) && isequaln(record.evaluations,expectedEvaluations));
        else
            assert(record.error==0 && record.evaluations==0);
        end
    catch exception
        error('fpf:CorruptCheckpoint','Invalid checkpoint %s: %s',path,exception.message);
    end
end

function results = acceptCheckpoint(results,record)
    id = record.globalId;
    if results.completed(id)
        error('fpf:DuplicateCheckpoint','Trial %d was accepted more than once.',id);
    end
    results.success(id) = record.success;
    results.errors(id) = record.error;
    results.evaluations(id) = record.evaluations;
    results.completed(id) = true;
end

function writeSnapshots(directory,benchmarkResults,trialResults,progress)
    temporaryMat = string(tempname(directory))+'.mat';
    temporaryCsv = string(tempname(directory))+'.csv';
    save(temporaryMat,'benchmarkResults','trialResults','progress','-v7');
    writetable(benchmarkResults,temporaryCsv);
    fpf.atomicReplace(temporaryMat,fullfile(directory,'benchmark_results.mat'));
    fpf.atomicReplace(temporaryCsv,fullfile(directory,'benchmark_results.csv'));
end

function reportWorkers(directory,activeIds,report)
    files = dir(fullfile(directory,'workers','worker_*.json'));
    for index = 1:numel(files)
        try
            state = jsondecode(fileread(fullfile(files(index).folder,files(index).name)));
        catch
            continue % Telemetry is advisory; checkpoint errors are never ignored.
        end
        if ~state.active || ~ismember(state.global_trial_id,activeIds), continue; end
        if isempty(state.best_stage_objective), state.best_stage_objective = NaN; end
        report('WORKER %d trial=%d stage=%s evaluations=%d best=%.9g elapsed=%.0fs last_update=%s',...
            state.worker_pid,state.global_trial_id,state.stage,state.objective_evaluations,...
            state.best_stage_objective,state.elapsed_seconds,state.updated_at);
    end
end

function releaseLock(lock,file)
    lock.release();
    file.close();
end
