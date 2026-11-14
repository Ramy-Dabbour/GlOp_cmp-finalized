function product = multiplyPolynomialMatrices(left,right,maxDegree)
%MULTIPLYPOLYNOMIALMATRICES Multiply truncated 2-by-2 polynomial matrices.

    product = zeros(2,2,maxDegree + 1);
    for row = 1:2
        for column = 1:2
            accumulator = zeros(1,maxDegree + 1);
            for inner = 1:2
                leftCoefficients = squeeze(left(row,inner,:)).';
                rightCoefficients = squeeze(right(inner,column,:)).';
                term = conv(leftCoefficients,rightCoefficients);
                accumulator = accumulator + term(1:(maxDegree + 1));
            end
            product(row,column,:) = accumulator;
        end
    end
end
