function checkpoint = runCloudCheckpointTrial(runTrial,parameter,plotResolution,liveDirectory,globalId,taskRoot,identity,options)
%RUNCLOUDCHECKPOINTTRIAL Preserve every outcome and wait for verified upload.
% A worker returns only after the external uploader's hash-bound receipt.
% Existing local records are uploaded/reconciled without rerunning science.
    arguments
        runTrial (1,1) function_handle
        parameter (1,6) double {mustBeReal,mustBeFinite}
        plotResolution (1,1) double {mustBeReal,mustBeInteger,mustBePositive}
        liveDirectory (1,1) string
        globalId (1,1) double {mustBeReal,mustBeInteger,mustBePositive}
        taskRoot (1,1) string
        identity (1,1) struct
        options.AckTimeoutSeconds (1,1) double {mustBeReal,mustBeFinite,mustBePositive} = 900
        options.AckPollSeconds (1,1) double {mustBeReal,mustBeFinite,mustBePositive} = 1
    end
    checkpointDirectory = fullfile(taskRoot,'results','checkpoints');
    ackDirectory = fullfile(taskRoot,'results','acks');
    if ~isfolder(checkpointDirectory), mkdir(checkpointDirectory); end
    if ~isfolder(ackDirectory), mkdir(ackDirectory); end
    path = fullfile(checkpointDirectory,sprintf('trial_%012d.mat',globalId));
    sidecarPath = fullfile(checkpointDirectory,sprintf('trial_%012d.json',globalId));
    if isfile(path)
        [checkpoint,acknowledged,sha256] = fpf.readCloudCheckpoint(path,parameter,globalId,identity,ackDirectory);
        if acknowledged, return; end
    else
        startedAt = fpf.TrialReporter.utcNow();
        clock = tic;
        exceptionRecord = struct('identifier','','message','','stack',[],'report','');
        capturedResult = [];
        try
            result = fpf.runReportedTrial(@captureResult,parameter,plotResolution,liveDirectory,globalId);
        catch exception
            if isempty(capturedResult)
                result = fpf.initializeRunResult(parameter(1),parameter(2),parameter(4),...
                    parameter(5),plotResolution,parameter(3),parameter(6));
                result.failureIdentifier = string(exception.identifier);
                result.failureMessage = string(exception.message);
                result.failureStage = "uncaught";
            else
                % A reporting/metric failure after the scientific return must
                % never discard the full result already produced by science.
                result = capturedResult;
            end
            exceptionRecord = struct('identifier',exception.identifier,'message',exception.message,...
                'stack',exception.stack,'report',getReport(exception,'extended','hyperlinks','off'));
        end
        elapsedSeconds = toc(clock);
        [rawError,referenceEvaluations,mziEvaluations,metricException] = observedMetrics(result);
        availableEvaluations = [referenceEvaluations,mziEvaluations];
        rawEvaluations = sum(availableEvaluations,'omitnan');
        if all(isnan(availableEvaluations)), rawEvaluations = NaN; end
        observedEvaluations = readObservedEvaluations(liveDirectory,globalId);
        if isnan(rawEvaluations) && isfinite(observedEvaluations), rawEvaluations = observedEvaluations; end
        success = logical(result.success);
        legacyError = 0;
        legacyEvaluations = 0;
        if success
            legacyError = rawError;
            legacyEvaluations = rawEvaluations;
        end
        status = 'nonconverged';
        if success
            status = 'succeeded';
        elseif strlength(resultField(result,'failureIdentifier'))>0 || strlength(resultField(result,'failureStage'))>0
            status = 'failed';
        end
        checkpoint = struct('schemaVersion',1,'identity',identity,'globalId',globalId,...
            'parameters',parameter,'success',success,'error',rawError,'evaluations',rawEvaluations,...
            'referenceEvaluations',referenceEvaluations,'mziEvaluations',mziEvaluations,...
            'observedEvaluations',observedEvaluations,...
            'evaluationCountComplete',all(isfinite(availableEvaluations)),...
            'legacyError',legacyError,'legacyEvaluations',legacyEvaluations,...
            'elapsedSeconds',elapsedSeconds,'result',result,'exception',exceptionRecord,...
            'metricException',metricException,...
            'status',status,'startedAt',startedAt,'completedAt',fpf.TrialReporter.utcNow());
        temporary = string(tempname(checkpointDirectory))+'.mat';
        save(temporary,'checkpoint','-v7');
        fpf.atomicReplace(temporary,path);
        sha256 = fpf.cloudFileSha256(path);
    end
    % The immutable JSON is written last: its appearance triggers uploading.
    sidecar = makeSidecar(checkpoint,sha256);
    if isfile(sidecarPath)
        existing = jsondecode(fileread(sidecarPath));
        assert(strcmp(existing.sha256,sha256),'fpf:CorruptCheckpoint','Checkpoint sidecar hash mismatch.');
    else
        fpf.writeCloudJson(sidecarPath,sidecar);
    end
    waitClock = tic;
    while true
        [checkpoint,acknowledged] = fpf.readCloudCheckpoint(path,parameter,globalId,identity,ackDirectory);
        if acknowledged, return; end
        if isfile(fullfile(taskRoot,'results','UPLOAD_FAILED.json'))
            error('fpf:CloudUploadFailed','Uploader failed; immutable trial %d is retained locally.',globalId);
        end
        if toc(waitClock)>=options.AckTimeoutSeconds
            error('fpf:CloudAcknowledgementTimeout',...
                'No durable upload receipt for trial %d after %.0f seconds. Local record retained.',globalId,options.AckTimeoutSeconds);
        end
        pause(options.AckPollSeconds);
    end

    function value = captureResult(varargin)
        value = runTrial(varargin{:});
        capturedResult = value;
    end
end

function [rawError,referenceEvaluations,mziEvaluations,metricException] = observedMetrics(result)
    rawError = NaN;
    referenceEvaluations = NaN;
    mziEvaluations = NaN;
    metricException = struct('identifier','','message','');
    if isfield(result,'referenceResult') && isstruct(result.referenceResult) && ...
            isfield(result.referenceResult,'metrics') && isfield(result.referenceResult.metrics,'functionEvaluations')
        referenceEvaluations = result.referenceResult.metrics.functionEvaluations;
    end
    if isfield(result,'mziResult') && isstruct(result.mziResult)
        if isfield(result.mziResult,'metrics') && isfield(result.mziResult.metrics,'functionEvaluations')
            mziEvaluations = result.mziResult.metrics.functionEvaluations;
        end
        if isfield(result,'rawSincReference') && ~isempty(result.rawSincReference) && ...
                isfield(result.mziResult,'realizedCoefficientMatrix')
            try
                rawError = fpf.endToEndError(result.rawSincReference,result.mziResult.realizedCoefficientMatrix);
            catch exception
                metricException = struct('identifier',exception.identifier,'message',exception.message);
            end
        end
    end
end

function value = readObservedEvaluations(directory,globalId)
    value = NaN;
    try
        state = jsondecode(fileread(fullfile(directory,'workers',sprintf('worker_%d.json',feature('getpid')))));
        if state.global_trial_id==globalId, value = state.objective_evaluations; end
    catch
        % Only advisory telemetry is optional; checkpoint I/O is never caught.
    end
end

function value = resultField(result,name)
    value = "";
    if isfield(result,name), value = string(result.(name)); end
end

function sidecar = makeSidecar(record,sha256)
    sidecar = struct('schema_version',1,'trial_id',record.globalId,...
        'parameters',record.parameters,'run_id',record.identity.run_id,...
        'source_sha256',record.identity.source_sha256,'config_sha256',record.identity.config_sha256,...
        'sha256',sha256,'completed',true,'success',record.success,'status',record.status,...
        'error',record.error,'evaluations',record.evaluations,...
        'reference_evaluations',record.referenceEvaluations,'mzi_evaluations',record.mziEvaluations,...
        'observed_evaluations',record.observedEvaluations,'evaluation_count_complete',record.evaluationCountComplete,...
        'legacy_error',record.legacyError,'legacy_evaluations',record.legacyEvaluations,...
        'elapsed_seconds',record.elapsedSeconds,'started_at',record.startedAt,'completed_at',record.completedAt,...
        'failure_identifier',char(resultField(record.result,'failureIdentifier')),...
        'failure_message',char(resultField(record.result,'failureMessage')));
end
