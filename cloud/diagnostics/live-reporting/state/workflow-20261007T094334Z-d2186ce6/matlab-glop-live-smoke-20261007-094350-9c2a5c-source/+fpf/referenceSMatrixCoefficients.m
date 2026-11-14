function coefficients = referenceSMatrixCoefficients(...
    referenceVector,stageCount,targetLagCount)
%REFERENCESMATRIXCOEFFICIENTS Build target squared S-matrix responses.

    if nargin < 3
        targetLagCount = stageCount;
    end
    directResponse = fpf.expandReferenceLagVector(...
        referenceVector,stageCount,targetLagCount);
    crossResponse = -directResponse;
    crossResponse(1) = crossResponse(1) + 1;
    coefficients = [directResponse;crossResponse;crossResponse;directResponse];
end
