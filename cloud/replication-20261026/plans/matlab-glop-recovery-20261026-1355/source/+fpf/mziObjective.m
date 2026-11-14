function deviation = mziObjective(design,stageCount,referenceCoefficientMatrix)
%MZIOBJECTIVE Return normalized S-matrix lag-coefficient error.

    result = fpf.evaluateMziSolution(...
        design,stageCount,referenceCoefficientMatrix,...
        CollectDiagnostics=false);
    deviation = result.normalizedFrobeniusError;
end
