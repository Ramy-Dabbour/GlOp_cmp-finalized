function reference = generateReference(tapCount,passbandRatio)
%GENERATEREFERENCE Generate the active reference vector.

    reference = fpf.generateSincReference(tapCount,passbandRatio);
end
