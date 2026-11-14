function isNormalized = isReferenceNormalized(coefficients)
%ISREFERENCENORMALIZED Test whether a cosine-series response lies in [0,1].

    coefficients = coefficients(:).';
    if isempty(coefficients) || ~isreal(coefficients) || ...
            any(~isfinite(coefficients))
        isNormalized = false;
        return
    end

    [~,extrema] = fpf.chebyshevExtrema(coefficients);
    alternatingSigns = (-1).^(0:(numel(coefficients) - 1));
    endpoints = [sum(coefficients),sum(coefficients.*alternatingSigns)];
    tolerance = 1e-12;
    isNormalized = all(extrema >= -tolerance & extrema <= 1 + tolerance) && ...
        all(endpoints >= -tolerance & endpoints <= 1 + tolerance);
end
