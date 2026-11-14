function seedTrialStage(randomSeed,trialIndex,stageName)
%SEEDTRIALSTAGE Select a reproducible random substream for one trial stage.
%   Stage substreams are independent of earlier solver RNG consumption.
%   Solver choices share a stream at a given seed, trial, and stage, while
%   every solver-pair call executes both optimization stages afresh.

    arguments
        randomSeed (1,1) double {mustBeReal,mustBeFinite,mustBeInteger,mustBeGreaterThanOrEqual(randomSeed,0),mustBeLessThanOrEqual(randomSeed,4294967295)}
        trialIndex (1,1) double {mustBeReal,mustBeFinite,mustBeInteger,mustBePositive}
        stageName (1,1) string {mustBeMember(stageName,["reference","mzi"])}
    end

    stageNumber = 1 + double(stageName == "mzi");
    trialStream = RandStream('mrg32k3a','Seed',randomSeed);
    trialStream.Substream = 2.*(trialIndex - 1) + stageNumber;
    RandStream.setGlobalStream(trialStream);
end
