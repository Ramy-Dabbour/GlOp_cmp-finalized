function points = generateInitialPoints(...
        lowerBounds,upperBounds,pointCount,stageName)
%GENERATEINITIALPOINTS Draw fresh starts from the caller's current RNG stream.
%   For reference coefficients, DC is uniform on (0,1). Conditional on DC,
%   the remaining cosine coefficients are uniform in an L1 ball of radius
%   min(DC,1-DC), up to a roundoff safety margin. This conservative subset of
%   the feasible region guarantees 0 <= DC + sum(c_k*cos(k*w)) <= 1 for all w.
%   Exponential simplex weights, independent signs, and the volume-correct
%   radial distribution provide this sampling without rejection or a grid.
%   For MZI designs, each coordinate is uniform within its supplied bounds.
%   Rows are independent candidates; reproducibility is controlled by the
%   caller's seed, never by resetting the stream inside this function.

    arguments
        lowerBounds (1,:) {mustBeFloat,mustBeReal,mustBeFinite,mustBeNonempty}
        upperBounds (1,:) {mustBeFloat,mustBeReal,mustBeFinite,mustBeNonempty}
        pointCount (1,1) {mustBeNumeric,mustBeReal,mustBeFinite,mustBeInteger,mustBePositive}
        stageName (1,1) string {mustBeMember(stageName,["reference","mzi"])}
    end

    numberOfVariables = numel(lowerBounds);
    if numel(upperBounds) ~= numberOfVariables || ...
            any(lowerBounds > upperBounds)
        error("fpf:InvalidBounds",...
            "Bounds must have equal lengths with lower bounds no greater than upper bounds.");
    end

    if stageName == "mzi"
        points = lowerBounds + rand(pointCount,numberOfVariables).*...
            (upperBounds - lowerBounds);
        return
    end

    if numberOfVariables < 2 || ...
            ~isequal(lowerBounds,[0,-ones(1,numberOfVariables - 1)]) || ...
            ~isequal(upperBounds,ones(1,numberOfVariables))
        error("fpf:InvalidReferenceBounds",...
            "Reference initialization requires bounds [0,-1,...,-1] and [1,1,...,1].");
    end

    nonconstantCount = numberOfVariables - 1;
    dc = rand(pointCount,1);
    simplexWeights = -log(max(rand(pointCount,nonconstantCount),realmin));
    simplexWeights = simplexWeights./sum(simplexWeights,2);
    signs = 2.*(rand(pointCount,nonconstantCount) >= 0.5) - 1;
    radius = min(dc,1 - dc).*rand(pointCount,1).^(1./nonconstantCount);
    radius = radius.*(1 - 16.*eps);
    points = [dc,radius.*simplexWeights.*signs];
end
