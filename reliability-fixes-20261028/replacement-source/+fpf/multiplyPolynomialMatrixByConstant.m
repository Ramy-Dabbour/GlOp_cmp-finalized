function product = multiplyPolynomialMatrixByConstant(left,right,maxDegree)
%MULTIPLYPOLYNOMIALMATRIXBYCONSTANT Multiply by a constant 2-by-2 matrix.

    product = zeros(2,2,maxDegree + 1);
    for row = 1:2
        for column = 1:2
            accumulator = zeros(1,maxDegree + 1);
            for inner = 1:2
                leftCoefficients = squeeze(left(row,inner,:)).';
                accumulator = accumulator + leftCoefficients.*right(inner,column);
            end
            product(row,column,:) = accumulator;
        end
    end
end
