function [coefficients,isNormalized] = realizedSMatrixLagCoefficients(zCoefficientMatrix)
%REALIZEDSMATRIXLAGCOEFFICIENTS Form normalized squared S-matrix responses.

    if ~ismatrix(zCoefficientMatrix) || size(zCoefficientMatrix,1) ~= 4 || ...
            isempty(zCoefficientMatrix)
        error("fpf:InvalidSCoefficients",...
            "The S-matrix coefficients must be a nonempty 4-by-M matrix.");
    end

    tapCount = size(zCoefficientMatrix,2);
    coefficients = zeros(4,2.*tapCount - 1);
    isNormalizedByRow = false(4,1);
    for row = 1:4
        coefficients(row,:) = fpf.autocorrelationDcFirst(...
            zCoefficientMatrix(row,:));
        isNormalizedByRow(row) = fpf.isLagResponseNormalized(...
            coefficients(row,:));
    end
    isNormalized = all(isNormalizedByRow);
end
