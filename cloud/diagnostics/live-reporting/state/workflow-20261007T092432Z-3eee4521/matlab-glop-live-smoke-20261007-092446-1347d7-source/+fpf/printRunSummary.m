function printRunSummary(result)
%PRINTRUNSUMMARY Display the optional legacy diagnostics for one trial.

    referenceResult = result.referenceResult;
    mziResult = result.mziResult;
    fprintf("\nFIR order: %d (%d taps)\n",result.firOrder,result.tapCount);
    fprintf("Passband ratio: %.16g\n",result.passbandRatio);
    fprintf("RNG seed: %d; trial: %d\n",result.randomSeed,result.trialIndex);
    fprintf("Reference solver: %s\n",referenceResult.solverName);
    fprintf("Reference normalized coefficient error: %.16g\n",...
        referenceResult.objectiveValue);
    fprintf("Reference elapsed time: %.16g s\n",...
        referenceResult.metrics.elapsedSeconds);
    fprintf("Reference function evaluations: %.16g\n",...
        referenceResult.metrics.functionEvaluations);
    fprintf("\nReference vector x:\n");
    disp(result.x);
    fprintf("MZI solver: %s\n",mziResult.solverName);
    fprintf("Optimized PSM phase: %.16g\n",mziResult.phiFixed);
    fprintf("Normalized Frobenius error: %.16g\n",...
        mziResult.normalizedFrobeniusError);
    fprintf("RMS coefficient error: %.16g\n",...
        mziResult.rmsCoefficientError);
    fprintf("MZI elapsed time: %.16g s\n",...
        mziResult.metrics.elapsedSeconds);
    fprintf("MZI function evaluations: %.16g\n",...
        mziResult.metrics.functionEvaluations);
end
