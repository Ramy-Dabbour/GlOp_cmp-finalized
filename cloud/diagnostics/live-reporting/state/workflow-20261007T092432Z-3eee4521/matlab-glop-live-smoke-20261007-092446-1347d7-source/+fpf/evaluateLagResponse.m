function response = evaluateLagResponse(coefficients,frequencies)
%EVALUATELAGRESPONSE Evaluate a DC-first lag-polynomial coefficient matrix.

    if ~ismatrix(coefficients) || isempty(coefficients) || ...
            mod(size(coefficients,2),2) ~= 1
        error("fpf:InvalidLagCoefficients",...
            "Coefficients must be a nonempty matrix with an odd column count.");
    end
    frequencies = frequencies(:).';
    if isempty(frequencies) || ~isreal(frequencies) || any(~isfinite(frequencies))
        error("fpf:InvalidFrequencies","Frequencies must be a finite real vector.");
    end

    lagCount = (size(coefficients,2) + 1)./2;
    lags = [0:(lagCount - 1),(1 - lagCount):-1].'; %#ok<BDSCI>
    response = coefficients*exp(2i.*pi.*lags.*frequencies);
end
