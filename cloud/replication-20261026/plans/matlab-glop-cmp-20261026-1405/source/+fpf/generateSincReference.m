function reference = generateSincReference(tapCount,passbandRatio)
%GENERATESINCREFERENCE Generate the DC-first cosine-series sinc reference.

    arguments
        tapCount (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(tapCount,2)}
        passbandRatio (1,1) double {mustBeFinite,mustBeGreaterThan(passbandRatio,0),mustBeLessThan(passbandRatio,1)}
    end

    harmonics = 1:(tapCount - 1);
    reference = passbandRatio.*[1,2.*sinc(passbandRatio.*harmonics)];
end
