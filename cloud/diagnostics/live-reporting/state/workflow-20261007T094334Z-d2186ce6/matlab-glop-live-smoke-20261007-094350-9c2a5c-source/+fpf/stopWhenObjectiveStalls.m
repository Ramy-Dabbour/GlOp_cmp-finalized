function stop = stopWhenObjectiveStalls(...
        ~,optimizationValues,state,functionTolerance,maxStallEvaluations)
%STOPWHENOBJECTIVESTALLS Stop a sequential surrogate solve after stagnation.
%   Each solver call resets this persistent state through its init callback.
%   Each process worker executes solvers sequentially with UseParallel=false;
%   persistent callback state is isolated between workers.

    arguments
        ~
        optimizationValues (1,1) struct
        state (1,1) string
        functionTolerance (1,1) {mustBeNumeric,mustBeReal,mustBeFinite,mustBeNonnegative}
        maxStallEvaluations (1,1) {mustBeNumeric,mustBeReal,mustBeFinite,mustBeInteger,mustBePositive}
    end

    persistent bestObjectiveValue lastSignificantImprovementEvaluation
    stop = false;
    if state == "init"
        bestObjectiveValue = Inf;
        lastSignificantImprovementEvaluation = optimizationValues.funccount;
        return
    end
    if state ~= "iter"
        return
    end
    incumbentObjectiveValue = optimizationValues.incumbentFval;
    if ~isscalar(incumbentObjectiveValue) || ~isfinite(incumbentObjectiveValue)
        return
    end

    currentObjectiveValue = incumbentObjectiveValue(1);
    functionEvaluationCount = optimizationValues.funccount(1);
    significantImprovement = functionTolerance.*max(1,abs(bestObjectiveValue));
    if ~isfinite(bestObjectiveValue)
        hasSignificantlyImproved = true;
    else
        hasSignificantlyImproved = currentObjectiveValue < ...
            bestObjectiveValue - significantImprovement;
    end
    if hasSignificantlyImproved
        bestObjectiveValue = currentObjectiveValue;
        lastSignificantImprovementEvaluation = functionEvaluationCount;
    end
    stop = functionEvaluationCount - ...
        lastSignificantImprovementEvaluation >= maxStallEvaluations;
end
