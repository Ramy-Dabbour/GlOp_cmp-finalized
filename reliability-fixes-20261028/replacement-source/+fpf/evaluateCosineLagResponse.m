function response = evaluateCosineLagResponse(coefficients,frequencies)
%EVALUATECOSINELAGRESPONSE Evaluate a real even lag-coefficient matrix.

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
    response = coefficients(:,1).*ones(1,numel(frequencies));
    for lag = 1:(lagCount - 1) %#ok<BDSCI>
        positiveIndex = lag + 1;
        negativeIndex = 2.*lagCount - lag;
        cosineCoefficient = coefficients(:,positiveIndex) + ...
            coefficients(:,negativeIndex);
        response = response + cosineCoefficient.*...
            cos(2.*pi.*lag.*frequencies);
    end
    response = real(response);
end
