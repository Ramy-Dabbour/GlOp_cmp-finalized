function result = runReportedTrial(runTrial,parameter,plotResolution,liveDirectory,globalId)
%RUNREPORTEDTRIAL Scope process-local reporting to one parfor iteration.
    reporter = [];
    if liveDirectory ~= ""
        reporter = fpf.TrialReporter(liveDirectory,globalId,parameter);
    end
    fpf.currentReporter(reporter);
    cleanup = onCleanup(@() fpf.currentReporter([]));
    try
        result = runTrial(parameter(1),parameter(2),parameter(4),...
            parameter(5),plotResolution,parameter(3),...
            SaveArtifacts=false,Display="off",Verbose=false,...
            CollectDiagnostics=liveDirectory~="",TrialIndex=parameter(6),ThrowOnFailure=false);
    catch exception
        if ~isempty(reporter)
            reporter.fail(exception);
        end
        rethrow(exception);
    end
    if ~isempty(reporter)
        observedError = NaN;
        if isfield(result,'rawSincReference') && ~isempty(result.rawSincReference) && ...
                isfield(result,'mziResult') && isstruct(result.mziResult) && ...
                isfield(result.mziResult,'realizedCoefficientMatrix')
            observedError = fpf.endToEndError(result.rawSincReference,...
                result.mziResult.realizedCoefficientMatrix);
        end
        reporter.finish(result,observedError);
    end
end
