function trialResults = runSweep(config,workIndices,requestedWorkers,options)
%RUNSWEEP Execute a single maximal parallel loop over global trial IDs.
%   Each iteration runs both optimization stages afresh and writes only its
%   own result slot. Zero workers runs on the client without a pool.
    arguments
        config (1,1) struct
        workIndices double
        requestedWorkers (1,1) double {mustBeReal,mustBeFinite,mustBeInteger,mustBeNonnegative}
        options.RunTrial (1,1) function_handle = @fpf.run
        options.LiveDirectory (1,1) string = ""
    end
    [parameters,~] = fpf.trialParameters(config,workIndices);
    workIndices = workIndices(:);
    if numel(unique(workIndices)) ~= numel(workIndices)
        error("fpf:DuplicateTrial","Each global trial ID must be executed once.");
    end
    numberOfTests = numel(workIndices);
    workerLimit = fpf.prepareTrialPool(min(requestedWorkers,numberOfTests));
    success = false(numberOfTests,1);
    errors = zeros(numberOfTests,1);
    evaluations = zeros(numberOfTests,1);
    runTrial = options.RunTrial;
    plotResolution = config.N_s;
    liveDirectory = options.LiveDirectory;
    if liveDirectory ~= ""
        mkdir(fullfile(liveDirectory,'trials'));
        mkdir(fullfile(liveDirectory,'workers'));
    end
    fprintf("Executing %d independent trials with %d pool workers.\n",...
        numberOfTests,workerLimit);
    parfor (workIndex = 1:numberOfTests,workerLimit)
        parameter = parameters(workIndex,:);
        runResult = fpf.runReportedTrial(runTrial,parameter,plotResolution,...
            liveDirectory,workIndices(workIndex));
        success(workIndex) = runResult.success;
        if runResult.success
            errors(workIndex) = fpf.endToEndError(...
                runResult.rawSincReference,...
                runResult.mziResult.realizedCoefficientMatrix);
            evaluations(workIndex) = ...
                runResult.referenceResult.metrics.functionEvaluations + ...
                runResult.mziResult.metrics.functionEvaluations;
        end
    end
    trialResults = struct("config",config,"workIndices",workIndices,...
        "success",success,"errors",errors,"evaluations",evaluations);
end
