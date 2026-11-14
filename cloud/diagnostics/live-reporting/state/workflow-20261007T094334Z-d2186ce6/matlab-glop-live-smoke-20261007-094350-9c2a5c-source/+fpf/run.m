function result = run(firOrder,passbandRatio,...
        referenceSolver,mziSolver,N_s,randomSeed,options)
%RUN Generate and optimize a fresh sequential FIR/MZI solver-pair trial.
%   N_s is retained for optional legacy response plots only. TrialIndex
%   selects independent, reproducible random substreams for the two stages.

    arguments
        firOrder (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(firOrder,1),mustBeLessThanOrEqual(firOrder,254)}
        passbandRatio (1,1) double {mustBeFinite,mustBeGreaterThan(passbandRatio,0),mustBeLessThan(passbandRatio,1)}
        referenceSolver (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(referenceSolver,0),mustBeLessThanOrEqual(referenceSolver,5)}
        mziSolver (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(mziSolver,0),mustBeLessThanOrEqual(mziSolver,5)}
        N_s (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(N_s,2)} = 10001
        randomSeed (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(randomSeed,0),mustBeLessThanOrEqual(randomSeed,4294967295)} = 0
        options.SaveArtifacts (1,1) logical = true
        options.Display (1,1) string {mustBeMember(options.Display,["off","final","iter","diagnose"])} = "iter"
        options.Verbose (1,1) logical = true
        options.TrialIndex (1,1) double {mustBeReal,mustBeFinite,mustBeInteger,mustBePositive} = 1
        options.ThrowOnFailure (1,1) logical = true
        options.CollectDiagnostics (1,1) logical = true
    end

    result = fpf.initializeRunResult(firOrder,passbandRatio,...
        referenceSolver,mziSolver,N_s,randomSeed,options.TrialIndex);
    callerRandomStream = RandStream.getGlobalStream;
    randomStreamCleanup = onCleanup(...
        @() RandStream.setGlobalStream(callerRandomStream));
    if options.SaveArtifacts
        packageDirectory = fileparts(mfilename("fullpath"));
        commandWindowOutputPath = fullfile(...
            packageDirectory,"CommandWindow_output.txt");
        if isfile(commandWindowOutputPath)
            delete(commandWindowOutputPath);
        end
        diary(commandWindowOutputPath);
        diaryCleanup = onCleanup(@() diary("off"));
    end

    try
        rawSincReference = fpf.generateReference(...
            firOrder + 1,passbandRatio);
        fpf.seedTrialStage(randomSeed,options.TrialIndex,"reference");
        referenceResult = fpf.optimizeReference(...
            rawSincReference,referenceSolver,Display=options.Display,...
            CollectDiagnostics=options.CollectDiagnostics);
    catch exception
        result = fpf.recordRunFailure(result,"reference",exception);
        fpf.handleRunFailure(result,exception,options);
        return
    end

    result.rawSincReference = rawSincReference;
    result.x = referenceResult.x;
    result.referenceResult = referenceResult;
    if options.CollectDiagnostics
        result.accuracy.reference = referenceResult.objectiveValue;
    end
    if ~referenceResult.isValidSolution
        exception = MException("fpf:InvalidOptimizedReference",...
            "The reference optimizer did not return a usable normalized reference.");
        result = fpf.recordRunFailure(result,"reference",exception);
        fpf.handleRunFailure(result,exception,options);
        return
    end

    try
        fpf.seedTrialStage(randomSeed,options.TrialIndex,"mzi");
        mziResult = fpf.optimizeMzi(...
            referenceResult.x,mziSolver,Display=options.Display,...
            CollectDiagnostics=options.CollectDiagnostics);
    catch exception
        result = fpf.recordRunFailure(result,"mzi",exception);
        fpf.handleRunFailure(result,exception,options);
        return
    end

    result.mziResult = mziResult;
    if options.CollectDiagnostics
        result.accuracy.normalizedFrobenius = ...
            mziResult.normalizedFrobeniusError;
        result.accuracy.rmsCoefficient = mziResult.rmsCoefficientError;
    end
    result.completed = true;
    result.success = referenceResult.metrics.converged && ...
        referenceResult.isValidSolution && mziResult.metrics.converged && ...
        mziResult.isValidSolution;

    if ~mziResult.isValidSolution
        exception = MException("fpf:InvalidMziSolution",...
            "The MZI optimizer did not return a usable normalized response.");
        result = fpf.recordRunFailure(result,"mzi",exception);
        fpf.handleRunFailure(result,exception,options);
        return
    end

    if options.Verbose
        fpf.printRunSummary(result);
    end

    if options.SaveArtifacts
        try
            result.artifacts = fpf.writeRunArtifacts(result);
            result.artifacts.commandWindowOutput = ...
                fullfile(fileparts(mfilename("fullpath")),...
                "CommandWindow_output.txt");
        catch exception
            result = fpf.recordRunFailure(result,"artifacts",exception);
            fpf.handleRunFailure(result,exception,options);
        end
    end
    if options.SaveArtifacts
        clear diaryCleanup
    end
end
