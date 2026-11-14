function benchmarkResults = runCloudCheckpointShard(taskRoot,taskIndex,taskCount,identity,options)
%RUNCLOUDCHECKPOINTSHARD Resume one strided shard from durable cloud receipts.
% Scientific configuration and trial functions are copied without changes.
% taskIndex is zero-based; IDs are taskIndex+1:taskCount:totalTests.
% The source manifest is verified by the launcher/uploader before this entry.
    arguments
        taskRoot (1,1) string
        taskIndex (1,1) double {mustBeReal,mustBeFinite,mustBeInteger,mustBeNonnegative}
        taskCount (1,1) double {mustBeReal,mustBeFinite,mustBeInteger,mustBePositive}
        identity (1,1) struct
        options.Config (1,1) struct = fpf.benchmarkConfig()
        options.RequestedWorkers (1,1) double {mustBeReal,mustBeInteger,mustBeNonnegative} = 8
        options.RunTrial (1,1) function_handle = @fpf.run
        options.HeartbeatSeconds (1,1) double {mustBeReal,mustBeFinite,mustBePositive} = 10
        options.AckTimeoutSeconds (1,1) double {mustBeReal,mustBeFinite,mustBePositive} = 900
        options.AckPollSeconds (1,1) double {mustBeReal,mustBeFinite,mustBePositive} = 1
        options.InterruptAfterCommits (1,1) double {mustBeReal,mustBePositive} = Inf
        options.HardCrashAfterCommits (1,1) double {mustBeReal,mustBePositive} = Inf
    end
    if taskIndex>=taskCount, error('fpf:InvalidShard','taskIndex must be smaller than taskCount.'); end
    for field = ["run_id","source_sha256","config_sha256"]
        if ~isfield(identity,field) || ~isscalar(string(identity.(field))) || strlength(string(identity.(field)))==0
            error('fpf:InvalidCloudIdentity','Manifest identity is missing %s.',field);
        end
        identity.(field) = char(string(identity.(field)));
    end
    config = options.Config;
    if strcmp(func2str(options.RunTrial),'fpf.run') && ...
            (~isequaln(config,fpf.benchmarkConfig()) || options.RequestedWorkers~=8 || ...
            isfinite(options.InterruptAfterCommits) || isfinite(options.HardCrashAfterCommits))
        error('fpf:ScientificConfigurationChanged','Production replication requires the unchanged benchmark config and eight process workers.');
    end
    resultDirectory = fullfile(taskRoot,'results');
    checkpointDirectory = fullfile(resultDirectory,'checkpoints');
    ackDirectory = fullfile(resultDirectory,'acks');
    if ~isfolder(checkpointDirectory), mkdir(checkpointDirectory); end
    if ~isfolder(ackDirectory), mkdir(ackDirectory); end
    lockFile = java.io.RandomAccessFile(char(fullfile(resultDirectory,'run.lock')),'rw');
    lock = lockFile.getChannel().tryLock();
    if isempty(lock)
        lockFile.close();
        error('fpf:CloudShardAlreadyActive','Another process owns this task root.');
    end
    lockCleanup = onCleanup(@() releaseLock(lock,lockFile));
    totalTests = prod(fpf.sweepSize(config));
    assignedIds = (taskIndex+1:taskCount:totalTests).';
    [parameters,pairIndices] = fpf.trialParameters(config,1:totalTests);
    manifest = struct('schemaVersion',1,'identity',identity,'config',config,...
        'taskIndex',taskIndex,'taskCount',taskCount,'runTrial',func2str(options.RunTrial),...
        'matlabRelease',version('-release'));
    manifestPath = fullfile(resultDirectory,'manifest.mat');
    if isfile(manifestPath)
        saved = load(manifestPath,'manifest');
        if ~isequaln(saved.manifest,manifest)
            error('fpf:CheckpointMismatch','Saved manifest differs from source/configuration/shard/runtime identity.');
        end
    else
        temporary = string(tempname(resultDirectory))+'.mat';
        save(temporary,'manifest','-v7');
        fpf.atomicReplace(temporary,manifestPath);
    end
    trialResults = struct('config',config,'workIndices',(1:totalTests).',...
        'assigned',false(totalTests,1),'completed',false(totalTests,1),...
        'success',false(totalTests,1),'errors',zeros(totalTests,1),...
        'evaluations',zeros(totalTests,1),'rawErrors',NaN(totalTests,1),...
        'rawEvaluations',NaN(totalTests,1),'elapsedSeconds',NaN(totalTests,1),...
        'status',repmat("pending",totalTests,1));
    trialResults.assigned(assignedIds) = true;
    progress = struct('schema_version',1,'run_id',identity.run_id,...
        'source_sha256',identity.source_sha256,'config_sha256',identity.config_sha256,...
        'task_index',taskIndex,'task_count',taskCount,'global_total_trials',totalTests,...
        'total_trials',numel(assignedIds),'completed_trials',0,'successful_trials',0,...
        'failed_trials',0,'is_complete',false,'status','initializing',...
        'workers',0,'pid',feature('getpid'),'updated_at',fpf.TrialReporter.utcNow());
    attemptDirectory = fullfile(resultDirectory,'live',char(java.util.UUID.randomUUID()));
    mkdir(fullfile(attemptDirectory,'trials'));
    mkdir(fullfile(attemptDirectory,'workers'));
    futures = parallel.FevalFuture.empty;
    attemptClock = tic;
    try
        records = dir(fullfile(checkpointDirectory,'trial_*.mat'));
        for index = 1:numel(records)
            token = regexp(records(index).name,'^trial_(\d{12})\.mat$','tokens','once');
            if isempty(token), error('fpf:CorruptCheckpoint','Invalid checkpoint filename %s.',records(index).name); end
            id = str2double(token{1});
            if ~ismember(id,assignedIds), error('fpf:CheckpointMismatch','Trial %d does not belong to this shard.',id); end
            [record,acknowledged] = fpf.readCloudCheckpoint(fullfile(records(index).folder,records(index).name),...
                parameters(id,:),id,identity,ackDirectory);
            if acknowledged, accept(record); end
        end
        progress.status = 'running';
        benchmarkResults = publish();
        pending = assignedIds(~trialResults.completed(assignedIds));
        report('RESUME task %d/%d: %d/%d cloud-committed; %d pending.',...
            taskIndex,taskCount,progress.completed_trials,numel(assignedIds),numel(pending));
        if isempty(pending)
            progress.status = 'completed';
            benchmarkResults = publish();
            return
        end
        if options.RequestedWorkers==0
            for index = 1:numel(pending)
                if isfile(fullfile(resultDirectory,'STOP')), break; end
                id = pending(index);
                record = fpf.runCloudCheckpointTrial(options.RunTrial,parameters(id,:),config.N_s,...
                    attemptDirectory,id,taskRoot,identity,AckTimeoutSeconds=options.AckTimeoutSeconds,...
                    AckPollSeconds=options.AckPollSeconds);
                completed(record);
            end
        else
            workerCount = fpf.prepareBatchPool(options.RequestedWorkers);
            progress.workers = workerCount;
            pool = gcp('nocreate');
            activeIds = zeros(workerCount,1);
            nextIndex = 1;
            for slot = 1:min(workerCount,numel(pending)), submit(slot); end
            lastHeartbeat = -Inf;
            while any(activeIds)
                if isfile(fullfile(resultDirectory,'STOP'))
                    cancel(futures);
                    break
                end
                for slot = 1:workerCount
                    if activeIds(slot)==0 || string(futures(slot).State)~="finished", continue; end
                    id = activeIds(slot);
                    if isempty(futures(slot).Error)
                        record = fetchOutputs(futures(slot));
                    else
                        path = fullfile(checkpointDirectory,sprintf('trial_%012d.mat',id));
                        if ~isfile(path), throw(futures(slot).Error); end
                        [record,acknowledged] = fpf.readCloudCheckpoint(path,parameters(id,:),id,identity,ackDirectory);
                        if ~acknowledged, throw(futures(slot).Error); end
                    end
                    completed(record);
                    activeIds(slot) = 0;
                    if nextIndex<=numel(pending), submit(slot); end
                end
                if toc(attemptClock)-lastHeartbeat>=options.HeartbeatSeconds
                    progress.updated_at = fpf.TrialReporter.utcNow();
                    progress.active_ids = activeIds(activeIds>0).';
                    fpf.writeCloudJson(fullfile(resultDirectory,'state.json'),progress);
                    report('PROGRESS %d/%d; successful=%d; other=%d; active=%s; elapsed=%.0fs',...
                        progress.completed_trials,numel(assignedIds),progress.successful_trials,...
                        progress.failed_trials,mat2str(progress.active_ids),toc(attemptClock));
                    lastHeartbeat = toc(attemptClock);
                end
                pause(0.1);
            end
        end
        progress.status = 'stopped';
        if all(trialResults.completed(assignedIds)), progress.status = 'completed'; end
        benchmarkResults = publish();
        report('%s: %d/%d durable trials.',upper(progress.status),progress.completed_trials,numel(assignedIds));
    catch exception
        if ~isempty(futures), cancel(futures); end
        progress.status = 'failed';
        progress.failure_identifier = exception.identifier;
        progress.failure_message = exception.message;
        try
            benchmarkResults = publish(); %#ok<NASGU>
        catch publishException
            exception = addCause(exception,publishException);
        end
        rethrow(exception);
    end

    function submit(slot)
        id = pending(nextIndex);
        nextIndex = nextIndex+1;
        activeIds(slot) = id;
        futures(slot) = parfeval(pool,@fpf.runCloudCheckpointTrial,1,options.RunTrial,...
            parameters(id,:),config.N_s,attemptDirectory,id,taskRoot,identity,...
            AckTimeoutSeconds=options.AckTimeoutSeconds,AckPollSeconds=options.AckPollSeconds);
        report('START trial %d: FIR=%d passband=%.3g seed=%d solvers=%d/%d sample=%d',...
            id,parameters(id,:));
    end

    function accept(record)
        id = record.globalId;
        if trialResults.completed(id), error('fpf:DuplicateCheckpoint','Trial %d was accepted twice.',id); end
        trialResults.success(id) = record.success;
        trialResults.errors(id) = record.legacyError;
        trialResults.evaluations(id) = record.legacyEvaluations;
        trialResults.rawErrors(id) = record.error;
        trialResults.rawEvaluations(id) = record.evaluations;
        trialResults.elapsedSeconds(id) = record.elapsedSeconds;
        trialResults.status(id) = string(record.status);
        trialResults.completed(id) = true;
    end

    function completed(record)
        accept(record);
        benchmarkResults = publish();
        report('DURABLE trial %d: %s error=%.9g evaluations=%g | %d/%d; MAT+CSV published',...
            record.globalId,record.status,record.error,record.evaluations,progress.completed_trials,numel(assignedIds));
        if progress.completed_trials>=options.HardCrashAfterCommits
            fprintf('SMOKE HARD CRASH: three acknowledged commits published; halting process without cleanup.\n');
            java.lang.Runtime.getRuntime().halt(137);
        end
        if progress.completed_trials>=options.InterruptAfterCommits
            error('fpf:SimulatedCloudInterruption','Synthetic smoke interrupted after %d durable commits.',progress.completed_trials);
        end
    end

    function summary = publish()
        summary = fpf.summarizeSweep(trialResults);
        pairs = height(summary);
        completedPerPair = accumarray(pairIndices,double(trialResults.completed),[pairs,1]);
        assignedPerPair = accumarray(pairIndices,double(trialResults.assigned),[pairs,1]);
        successesPerPair = accumarray(pairIndices,double(trialResults.success),[pairs,1]);
        hasCompleted = completedPerPair>0;
        summary.favorabilityIndex(hasCompleted) = summary.favorabilityIndex(hasCompleted).*...
            (totalTests/pairs)./completedPerPair(hasCompleted);
        summary.favorabilityIndex(~hasCompleted) = NaN;
        summary.completedTrials = completedPerPair;
        summary.assignedTrials = assignedPerPair;
        summary.successfulTrials = successesPerPair;
        progress.completed_trials = nnz(trialResults.completed);
        progress.successful_trials = nnz(trialResults.success);
        progress.failed_trials = nnz(trialResults.completed & ~trialResults.success);
        progress.is_complete = all(trialResults.completed(assignedIds));
        progress.updated_at = fpf.TrialReporter.utcNow();
        benchmarkResults = summary;
        temporaryMat = string(tempname(resultDirectory))+'.mat';
        save(temporaryMat,'benchmarkResults','trialResults','progress','manifest','-v7');
        fpf.atomicReplace(temporaryMat,fullfile(resultDirectory,'benchmark_results.mat'));
        writeTable(summary,fullfile(resultDirectory,'benchmark_results.csv'));
        ids = assignedIds;
        detail = table(ids,trialResults.completed(ids),trialResults.success(ids),...
            trialResults.status(ids),trialResults.rawErrors(ids),trialResults.rawEvaluations(ids),...
            trialResults.elapsedSeconds(ids),trialResults.errors(ids),trialResults.evaluations(ids),...
            VariableNames={'trial_id','completed','success','status','error','evaluations',...
            'elapsed_seconds','legacy_error','legacy_evaluations'});
        writeTable(detail,fullfile(resultDirectory,'trial_results.csv'));
        fpf.writeCloudJson(fullfile(resultDirectory,'state.json'),progress);
    end

    function report(format,varargin)
        line = sprintf('[%s] %s\n',fpf.TrialReporter.utcNow(),sprintf(format,varargin{:}));
        fprintf('%s',line);
        try
            file = fopen(fullfile(resultDirectory,'progress.log'),'a','n','UTF-8');
            if file<0, error('fpf:AdvisoryLog','Cannot append progress log.'); end
            cleanup = onCleanup(@() fclose(file));
            fprintf(file,'%s',line);
        catch exception
            warning('fpf:AdvisoryLog','Progress log could not be written: %s',exception.message);
        end
    end
end

function writeTable(value,path)
    temporary = string(tempname(fileparts(path)))+'.csv';
    writetable(value,temporary);
    fpf.atomicReplace(temporary,path);
end

function releaseLock(lock,file)
    lock.release();
    file.close();
end
