function normalizedError = endToEndError(rawReference,realizedCoefficientMatrix)
%ENDTOENDERROR Compare all four squared S-matrix polynomials to the raw target.
%   Realized rows are |S11|^2, |S12|^2, |S21|^2, and |S22|^2 in DC-first
%   lag order [0,1,...,L-1,-(L-1),...,-1], obtained by linear convolution
%   of each field vector with its reversed complex conjugate. The original
%   unconstrained cosine reference supplies g on the diagonal and 1-g off
%   the diagonal. Compare aligned coefficients without frequency sampling.
%   The error is the Frobenius norm of the 2-by-2 matrix of differential
%   vector l2 norms, divided by the same statistic for the raw target.

    arguments
        rawReference (1,:) double {mustBeReal,mustBeFinite,mustBeNonempty}
        realizedCoefficientMatrix double {mustBeFinite,mustBeNonempty}
    end

    lagLength = size(realizedCoefficientMatrix,2);
    if ~ismatrix(realizedCoefficientMatrix) || ...
            size(realizedCoefficientMatrix,1) ~= 4 || mod(lagLength,2) ~= 1
        error("fpf:InvalidSCoefficients",...
            "Realized S-matrix lag coefficients must be a 4-by-(2L-1) matrix.");
    end
    tapCount = numel(rawReference);
    realizedLagCount = (lagLength + 1)./2;
    lagCount = max(tapCount,realizedLagCount);
    referenceCoefficients = fpf.referenceSMatrixCoefficients(...
        rawReference,tapCount,lagCount);

    % Pad between positive and negative lags, retaining every harmonic in
    % either polynomial. Appending zeros would misalign the negative lags.
    paddingLength = lagCount - realizedLagCount;
    realizedCoefficients = [realizedCoefficientMatrix(:,1:realizedLagCount),... %#ok<BDSCI>
        zeros(4,2.*paddingLength),...
        realizedCoefficientMatrix(:,(realizedLagCount + 1):end)]; %#ok<BDSCI>
    differentialNorms = vecnorm(realizedCoefficients - referenceCoefficients,2,2);
    referenceNorms = vecnorm(referenceCoefficients,2,2);
    differentialNormMatrix = reshape(differentialNorms,2,2).';
    referenceNormMatrix = reshape(referenceNorms,2,2).';
    referenceNorm = norm(referenceNormMatrix,'fro');
    if referenceNorm == 0
        error("fpf:InvalidReference",...
            "The unconstrained S-matrix target must have nonzero norm.");
    end
    normalizedError = norm(differentialNormMatrix,'fro')./referenceNorm;
end
