function coefficients = chebyshevTCoefficients(order)
%CHEBYSHEVTCOEFFICIENTS Return descending-power coefficients of T_order.

    arguments
        order (1,1) double {mustBeInteger,mustBeNonnegative}
    end

    if order == 0
        coefficients = 1;
        return
    end

    previous = 1;
    current = [1,0];
    for index = 2:order
        shiftedCurrent = [current,0];
        paddedPrevious = [zeros(1,numel(shiftedCurrent) - numel(previous)),previous];
        next = 2.*shiftedCurrent - paddedPrevious;
        previous = current;
        current = next;
    end
    coefficients = current;
end
