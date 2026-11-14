function result = optimizeMzi(referenceVector,solverIndex,options)
%OPTIMIZEMZI Fit an MZI lattice to a reference coefficient vector.

    arguments
        referenceVector double
        solverIndex (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(solverIndex,0),mustBeLessThanOrEqual(solverIndex,5)}
        options.Display (1,1) string {mustBeMember(options.Display,["off","final","iter","diagnose"])} = "iter"
        options.CollectDiagnostics (1,1) logical = true
    end

    referenceVector = referenceVector(:).';
    stageCount = numel(referenceVector);
    if stageCount < 2 || ~isreal(referenceVector) || ...
            any(~isfinite(referenceVector))
        error("fpf:InvalidReference","The reference must be a finite real vector with at least two taps.");
    end

    referenceCoefficientMatrix = fpf.referenceSMatrixCoefficients(...
        referenceVector,stageCount,2.*stageCount);
    numberOfVariables = stageCount + 1;
    lowerBounds = zeros(1,numberOfVariables);
    upperBounds = ones(1,numberOfVariables);
    initialPoint = fpf.generateInitialPoints(...
        lowerBounds,upperBounds,1,"mzi");
    objective = @(design) fpf.mziObjective(...
        design,stageCount,referenceCoefficientMatrix);
    elapsedSeconds = 0;
    if options.CollectDiagnostics
        optimizationTimer = tic;
    end
    [design,objectiveValue,exitFlag,output,solverName] = fpf.runGlobalSolver(...
        objective,lowerBounds,upperBounds,initialPoint,solverIndex,...
        "mzi",Display=options.Display);
    if options.CollectDiagnostics
        elapsedSeconds = toc(optimizationTimer);
    end

    result = fpf.evaluateMziSolution(...
        design,stageCount,referenceCoefficientMatrix,...
        CollectDiagnostics=options.CollectDiagnostics);
    result.referenceVector = referenceVector;
    result.objectiveValue = objectiveValue;
    result.exitFlag = exitFlag;
    result.output = output;
    result.solverName = solverName;
    result.isValidSolution = result.isResponseNormalized && ...
        all(isfinite(result.design)) && isfinite(result.objectiveValue);
    result.metrics = fpf.extractSolverMetrics(...
        output,exitFlag,elapsedSeconds,solverName,...
        CollectDiagnostics=options.CollectDiagnostics);
end
