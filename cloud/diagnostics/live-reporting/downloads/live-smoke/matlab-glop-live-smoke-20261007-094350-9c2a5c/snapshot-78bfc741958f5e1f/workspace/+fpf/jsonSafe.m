function value = jsonSafe(value)
%JSONSAFE Preserve complex scientific arrays in JSON as real/imag objects.
%   MATLAB JSON represents NaN/Inf as null; status/exit flags explain failures.
    if isa(value,'function_handle')
        % Solver diagnostics may include callback handles. Keep their names,
        % without attempting to serialize executable closures.
        value = struct('matlab_function',func2str(value));
    elseif isnumeric(value) && ~isreal(value)
        value = struct('real',real(value),'imag',imag(value),'size',size(value));
    elseif isstruct(value)
        names = fieldnames(value);
        for index = 1:numel(value)
            for field = 1:numel(names)
                value(index).(names{field}) = fpf.jsonSafe(value(index).(names{field}));
            end
        end
    elseif iscell(value)
        value = cellfun(@fpf.jsonSafe,value,UniformOutput=false);
    end
end
