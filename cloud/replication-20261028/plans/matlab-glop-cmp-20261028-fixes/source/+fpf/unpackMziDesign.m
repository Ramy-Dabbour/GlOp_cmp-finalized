function [theta,phiFixed,phaseShiftPattern] = unpackMziDesign(design,stageCount)
%UNPACKMZIDESIGN Split the always-variable PSM design vector.

    design = design(:).';
    if numel(design) ~= stageCount + 1 || ...
            ~isreal(design) || any(~isfinite(design))
        error("fpf:InvalidMziDesign",...
            "The MZI design must contain one angle per stage and one PSM phase.");
    end

    theta = mod(design(1:stageCount),1);
    phiFixed = mod(design(stageCount + 1),1);
    phaseShiftPattern = fpf.phaseShiftPattern(stageCount,phiFixed);
end
