function [rootsInInterval,extrema] = chebyshevExtrema(coefficients)
%CHEBYSHEVEXTREMA Return stationary-point locations and response values.

    coefficients = coefficients(:).';
    [valuePolynomial,derivativePolynomial] = ...
        fpf.signalValuePolynomials(coefficients);
    rootsInInterval = roots(derivativePolynomial);
    rootsInInterval = rootsInInterval(abs(imag(rootsInInterval)) < 1e-12);
    rootsInInterval = real(rootsInInterval);
    rootsInInterval = rootsInInterval(rootsInInterval >= -1 & rootsInInterval <= 1);
    extrema = polyval(valuePolynomial,rootsInInterval);
end
