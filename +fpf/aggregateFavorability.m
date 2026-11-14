function favorability = aggregateFavorability(...
        successfulTrials,totalTrials,successfulErrorSum,successfulEvaluationSum)
%AGGREGATEFAVORABILITY Compute one favorability index per solver pair.
%   P = successfulTrials/totalTrials over the entire trial space.
%   E = mean normalized end-to-end error among successful trials.
%   C = mean (Stage-1 + Stage-2 objective evaluations) among successful trials.
%   Favorability = P/E/log(C). A pair with no successes scores zero; an exact
%   reconstruction scores Inf. Invalid successful-run data produces NaN,
%   rather than silently omitting trials or modifying the requested formula.

    arguments
        successfulTrials double {mustBeReal,mustBeFinite,mustBeInteger,mustBeNonnegative}
        totalTrials (1,1) double {mustBeReal,mustBeFinite,mustBeInteger,mustBePositive}
        successfulErrorSum double {mustBeReal}
        successfulEvaluationSum double {mustBeReal}
    end

    if ~isequal(size(successfulTrials),size(successfulErrorSum),...
            size(successfulEvaluationSum)) || any(successfulTrials(:) > totalTrials)
        error("fpf:InvalidFavorabilityTotals",...
            "Pair totals must have equal sizes and successes cannot exceed trials.");
    end
    favorability = zeros(size(successfulTrials));
    hasSuccess = successfulTrials > 0;
    meanError = successfulErrorSum(hasSuccess)./successfulTrials(hasSuccess);
    meanEvaluations = ...
        successfulEvaluationSum(hasSuccess)./successfulTrials(hasSuccess);
    convergenceRate = successfulTrials(hasSuccess)./totalTrials;
    values = convergenceRate./meanError./log(meanEvaluations);
    invalid = ~isfinite(meanError) | meanError < 0 | ...
        ~isfinite(meanEvaluations) | meanEvaluations <= 1;
    values(invalid) = NaN;
    favorability(hasSuccess) = values;
end
