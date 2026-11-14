function deviation = referenceObjective(candidate,target)
%REFERENCEOBJECTIVE Measure admissible-reference error against a target.

    candidate = candidate(:).';
    target = target(:).';
    if numel(candidate) ~= numel(target) || ~isreal(candidate) || ...
            any(~isfinite(candidate)) || ~fpf.isReferenceNormalized(candidate)
        deviation = realmax;
        return
    end

    targetNorm = norm(target);
    if targetNorm == 0
        error("fpf:InvalidReference","The target reference must have nonzero norm.");
    end
    deviation = norm(candidate - target)./targetNorm;
end
