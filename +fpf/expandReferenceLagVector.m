function lagVector = expandReferenceLagVector(referenceVector,stageCount,targetLagCount)
%EXPANDREFERENCELAGVECTOR Convert a cosine vector to DC-first lag order.

    arguments
        referenceVector (1,:) double
        stageCount (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(stageCount,2)}
        targetLagCount (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(targetLagCount,stageCount)}
    end

    referenceVector = referenceVector(:).';
    sourceLagLength = 2.*stageCount - 1;
    targetLagLength = 2.*targetLagCount - 1;

    if numel(referenceVector) == stageCount
        positiveLags = zeros(1,targetLagCount - 1);
        positiveLags(1:(stageCount - 1)) = 0.5.*referenceVector(2:end);
        lagVector = [referenceVector(1),positiveLags,conj(fliplr(positiveLags))];
    elseif numel(referenceVector) == sourceLagLength
        positiveLags = zeros(1,targetLagCount - 1);
        negativeLags = zeros(1,targetLagCount - 1);
        positiveLags(1:(stageCount - 1)) = referenceVector(2:stageCount);
        negativeLags((end - stageCount + 2):end) = ...
            referenceVector((stageCount + 1):end);
        lagVector = [referenceVector(1),positiveLags,negativeLags];
    elseif numel(referenceVector) == targetLagLength
        lagVector = referenceVector;
    else
        error("fpf:InvalidReferenceLength",...
            "Reference length must equal the tap count or a supported lag-vector length.");
    end
end
