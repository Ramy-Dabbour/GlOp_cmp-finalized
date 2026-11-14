function pattern = phaseShiftPattern(stageCount,phiFixed)
%PHASESHIFTPATTERN Return the alternating fixed-phase pattern.

    arguments
        stageCount (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(stageCount,1)}
        phiFixed (1,1) double {mustBeFinite}
    end

    stageIndices = 1:stageCount;
    pattern = mod(stageCount - stageIndices,2).*mod(phiFixed,1);
end
