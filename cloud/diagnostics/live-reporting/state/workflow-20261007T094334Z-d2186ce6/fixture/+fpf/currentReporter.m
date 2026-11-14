function reporter = currentReporter(varargin)
%CURRENTREPORTER Process-local reporting context; empty for ordinary runs.
    persistent current
    if nargin
        current = varargin{1};
    end
    reporter = current;
end
