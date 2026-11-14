function coefficients = mziSMatrixCoefficients(theta,phaseShiftPattern)
%MZISMATRIXCOEFFICIENTS Build z-domain coefficients of the MZI S matrix.

    theta = theta(:).';
    phaseShiftPattern = phaseShiftPattern(:).';
    stageCount = numel(theta);
    if stageCount < 2 || numel(phaseShiftPattern) ~= stageCount || ...
            ~isreal(theta) || any(~isfinite(theta)) || ...
            ~isreal(phaseShiftPattern) || any(~isfinite(phaseShiftPattern))
        error("fpf:InvalidMziParameters",...
            "Theta and phase patterns must be finite real vectors of the same length.");
    end

    maxDegree = 2.*stageCount - 1;
    transferMatrix = zeros(2,2,maxDegree + 1);
    transferMatrix(1,1,1) = 1;
    transferMatrix(2,2,1) = 1;
    stageOrders = [2.*ones(1,stageCount - 1),1];

    for stageIndex = 1:stageCount
        stageMatrix = zeros(2,2,maxDegree + 1);
        stageOrder = stageOrders(stageIndex);
        transmission = cos(2.*pi.*theta(stageIndex));
        coupling = sin(2.*pi.*theta(stageIndex));
        phase = exp(-2i.*pi.*phaseShiftPattern(stageIndex));
        stageMatrix(1,1,stageOrder + 1) = phase.*transmission;
        stageMatrix(1,2,1) = 1i.*coupling;
        stageMatrix(2,1,stageOrder + 1) = phase.*1i.*coupling;
        stageMatrix(2,2,1) = transmission;
        transferMatrix = fpf.multiplyPolynomialMatrices(...
            transferMatrix,stageMatrix,maxDegree);
    end

    finalCoupler = sqrt(0.5).*[1,1i;1i,1];
    transferMatrix = fpf.multiplyPolynomialMatrixByConstant(...
        transferMatrix,finalCoupler,maxDegree);
    coefficients = zeros(4,maxDegree + 1);
    coefficients(1,:) = squeeze(transferMatrix(1,1,:)).';
    coefficients(2,:) = squeeze(transferMatrix(1,2,:)).';
    coefficients(3,:) = squeeze(transferMatrix(2,1,:)).';
    coefficients(4,:) = squeeze(transferMatrix(2,2,:)).';
end
