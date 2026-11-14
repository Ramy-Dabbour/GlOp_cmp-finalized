function value = readScalarField(output,fieldName)
%READSCALARFIELD Read a scalar numeric solver-output field when available.

    value = NaN;
    if isstruct(output) && isfield(output,fieldName)
        candidate = output.(fieldName);
        if isnumeric(candidate) && isscalar(candidate)
            value = double(candidate);
        end
    end
end
