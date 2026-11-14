function [parameters,pairIndices] = trialParameters(config,workIndices)
%TRIALPARAMETERS Decode global IDs into independent operating-point samples.
%   Each row is [firOrder passbandRatio seed referenceSolver mziSolver trial].
%   Trial varies fastest, then MZI solver, reference solver, FIR order,
%   passband ratio, and seed. This is the original nested-loop order.
    workSize = fpf.sweepSize(config);
    validateattributes(workIndices,"double",...
        {"real","finite","integer",">=",1,"<=",prod(workSize)});
    workIndices = workIndices(:);
    [trial,mzi,reference,fir,passband,seed] = ind2sub(workSize,workIndices);
    parameters = [reshape(config.firOrders(fir),[],1),...
        reshape(config.passbandRatios(passband),[],1),...
        reshape(config.randomSeeds(seed),[],1),...
        reshape(config.referenceSolvers(reference),[],1),...
        reshape(config.mziSolvers(mzi),[],1),trial];
    pairIndices = sub2ind([workSize(3),workSize(2)],reference,mzi);
end
