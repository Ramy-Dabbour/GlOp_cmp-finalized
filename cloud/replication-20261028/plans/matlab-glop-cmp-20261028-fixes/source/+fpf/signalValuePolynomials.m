function [valuePolynomial,derivativePolynomial] = signalValuePolynomials(coefficients)
%SIGNALVALUEPOLYNOMIALS Build Chebyshev value and derivative polynomials.

    coefficients = coefficients(:).';
    tapCount = numel(coefficients);
    valuePolynomial = zeros(1,tapCount);
    derivativePolynomial = zeros(1,tapCount);
    valuePolynomial(end) = coefficients(1);

    for harmonic = 1:(tapCount - 1)
        valuePolynomial = valuePolynomial + coefficients(harmonic + 1).*...
            [zeros(1,tapCount - harmonic - 1),...
            fpf.chebyshevTCoefficients(harmonic)];
        derivativePolynomial = derivativePolynomial + harmonic.*...
            coefficients(harmonic + 1).*[zeros(1,tapCount - harmonic),...
            fpf.chebyshevUCoefficients(harmonic - 1)];
    end
end
