function extrema = complexHarmonicExtrema(coefficients)
%COMPLEXHARMONICEXTREMA Evaluate a Hermitian lag polynomial at extrema.

    coefficients = coefficients(:).';
    if isempty(coefficients) || mod(numel(coefficients),2) ~= 1 || ...
            any(~isfinite(coefficients))
        error("fpf:InvalidLagCoefficients",...
            "Lag coefficients must be a finite odd-length vector.");
    end

    lagCount = (numel(coefficients) + 1)./2;
    maxLag = lagCount - 1;
    lags = [0:maxLag,(1 - lagCount):-1]; %#ok<BDSCI>
    frequencies = [-0.5,0];
    derivativePolynomial = zeros(1,2.*maxLag + 1);

    for index = 1:numel(lags)
        lag = lags(index);
        derivativePolynomial(maxLag - lag + 1) = ...
            1i.*lag.*coefficients(index);
    end

    nonzeroIndices = find(abs(derivativePolynomial) > 0);
    if ~isempty(nonzeroIndices)
        derivativePolynomial = derivativePolynomial(...
            nonzeroIndices(1):nonzeroIndices(end));
        derivativeRoots = roots(derivativePolynomial);
        unitCircleRoots = derivativeRoots(...
            abs(abs(derivativeRoots) - 1) < 1e-10);
        rootFrequencies = angle(unitCircleRoots)./(2.*pi);
        rootFrequencies = mod(rootFrequencies + 0.5,1) - 0.5;
        frequencies = [frequencies,rootFrequencies(:).'];
    end

    frequencies = uniquetol(frequencies,1e-10);
    extrema = real(fpf.evaluateLagResponse(coefficients,frequencies));
end
