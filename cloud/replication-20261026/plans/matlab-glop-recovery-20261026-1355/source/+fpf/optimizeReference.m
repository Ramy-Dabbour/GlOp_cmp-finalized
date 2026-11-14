function result = optimizeReference(target,solverIndex,options)
%OPTIMIZEREFERENCE Fit a normalized FIR reference to the sinc target.

    arguments
        target double
        solverIndex (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(solverIndex,0),mustBeLessThanOrEqual(solverIndex,5)}
        options.Display (1,1) string {mustBeMember(options.Display,["off","final","iter","diagnose"])} = "iter"
        options.CollectDiagnostics (1,1) logical = true
    end

    target = target(:).';
    tapCount = numel(target);
    if tapCount < 2 || ~isreal(target) || any(~isfinite(target))
        error("fpf:InvalidReference","The reference must be a finite real vector with at least two taps.");
    end

    lowerBounds = [0,-ones(1,tapCount - 1)];
    upperBounds = ones(1,tapCount);
    initialPoint = fpf.generateInitialPoints(...
        lowerBounds,upperBounds,1,"reference");
    objective = @(candidate) fpf.referenceObjective(candidate,target);
    elapsedSeconds = 0;
    if options.CollectDiagnostics
        optimizationTimer = tic;
    end
    [x,objectiveValue,exitFlag,output,solverName] = fpf.runGlobalSolver(...
        objective,lowerBounds,upperBounds,initialPoint,solverIndex,...
        "reference",Display=options.Display);
    if options.CollectDiagnostics
        elapsedSeconds = toc(optimizationTimer);
    end

    result = struct("target",target,"x",x,"objectiveValue",objectiveValue,...
        "exitFlag",exitFlag,"output",output,"solverName",solverName,...
        "isValidSolution",fpf.isReferenceNormalized(x),...
        "metrics",fpf.extractSolverMetrics(...
            output,exitFlag,elapsedSeconds,solverName,...
            CollectDiagnostics=options.CollectDiagnostics));
end
