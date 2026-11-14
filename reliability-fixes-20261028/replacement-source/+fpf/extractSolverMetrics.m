function metrics = extractSolverMetrics(...
        output,exitFlag,elapsedSeconds,solverName,options)
%EXTRACTSOLVERMETRICS Normalize solver-specific efficiency information.

    arguments
        output
        exitFlag (1,1) double
        elapsedSeconds (1,1) double {mustBeFinite,mustBeNonnegative}
        solverName (1,1) string
        options.CollectDiagnostics (1,1) logical = true
    end

    functionEvaluations = fpf.readScalarField(output,"funccount");
    progressCount = NaN;
    progressUnit = "";
    if options.CollectDiagnostics
        if solverName == "ga" && isstruct(output) && ...
                isfield(output,"generations")
            progressCount = double(output.generations);
            progressUnit = "generation";
        elseif isstruct(output) && isfield(output,"iterations")
            progressCount = double(output.iterations);
            progressUnit = "iteration";
        end
    else
        elapsedSeconds = NaN;
    end

    metrics = struct(...
        "solverName",solverName,...
        "elapsedSeconds",elapsedSeconds,...
        "functionEvaluations",functionEvaluations,...
        "progressCount",progressCount,...
        "progressUnit",progressUnit,...
        "exitFlag",exitFlag,...
        "converged",exitFlag > 0);
end
