function isNormalized = isLagResponseNormalized(coefficients)
%ISLAGRESPONSENORMALIZED Test whether a lag polynomial remains in [0,1].

    extrema = fpf.complexHarmonicExtrema(coefficients);
    tolerance = 1e-10;
    isNormalized = all(isfinite(extrema)) && ...
        all(extrema >= -tolerance & extrema <= 1 + tolerance);
end
