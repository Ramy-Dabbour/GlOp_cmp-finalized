function correlation = autocorrelationDcFirst(vector)
%AUTOCORRELATIONDCFIRST Return autocorrelation in DC-first lag order.
%   For S(z) = sum_k v(k+1)*z^k, the linear convolution below represents
%   S(z)*conj(S(1/conj(z))) with powers -(M-1):M-1. On the unit circle this
%   is |S(z)|^2. Reorder its coefficients to [0:M-1, -(M-1):-1] for exact
%   polynomial comparison; no frequency grid or symbolic algebra is needed.

    vector = vector(:).';
    if isempty(vector) || any(~isfinite(vector))
        error("fpf:InvalidVector","The input must be a finite nonempty vector.");
    end

    centered = conv(vector,conj(fliplr(vector)));
    dcIndex = numel(vector);
    correlation = [centered(dcIndex:end),centered(1:(dcIndex - 1))];
end
