function checkpoint = runCheckpointTrial(runTrial,parameter,plotResolution,liveDirectory,globalId,checkpointDirectory,manifestId)
%RUNCHECKPOINTTRIAL Commit the entire trial result before acknowledging it.
    result = fpf.runReportedTrial(runTrial,parameter,plotResolution,liveDirectory,globalId);
    checkpoint = struct('schemaVersion',1,'manifestId',manifestId,...
        'globalId',globalId,'parameters',parameter,'success',logical(result.success),...
        'error',0,'evaluations',0,'result',result,...
        'completedAt',fpf.TrialReporter.utcNow());
    if result.success
        checkpoint.error = fpf.endToEndError(result.rawSincReference,...
            result.mziResult.realizedCoefficientMatrix);
        checkpoint.evaluations = result.referenceResult.metrics.functionEvaluations + ...
            result.mziResult.metrics.functionEvaluations;
    end
    destination = fullfile(checkpointDirectory,sprintf('trial_%012d.mat',globalId));
    if isfile(destination)
        error('fpf:DuplicateCheckpoint','Trial %d already has a committed checkpoint.',globalId);
    end
    temporary = string(tempname(checkpointDirectory)) + '.mat';
    save(temporary,'checkpoint','-v7');
    % atomicReplace flushes the closed MAT before publishing its final name.
    fpf.atomicReplace(temporary,destination);
end
