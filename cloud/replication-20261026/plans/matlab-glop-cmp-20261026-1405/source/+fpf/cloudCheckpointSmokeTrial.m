function result = cloudCheckpointSmokeTrial(firOrder,passbandRatio,referenceSolver,mziSolver,plotResolution,randomSeed,options)
%CLOUDCHECKPOINTSMOKETRIAL Cheap deterministic results, including failures.
    arguments
        firOrder
        passbandRatio
        referenceSolver
        mziSolver
        plotResolution
        randomSeed
        options.TrialIndex = 1
        options.SaveArtifacts = false
        options.Display = "off"
        options.Verbose = false
        options.CollectDiagnostics = true
        options.ThrowOnFailure = false
    end
    trial = options.TrialIndex;
    pause(.1+.05*mod(7-trial,7));
    if mod(trial,7)==3
        error('fpf:SmokeScientificException','Deliberate smoke scientific exception for trial %d.',trial);
    end
    result = fpf.initializeRunResult(firOrder,passbandRatio,referenceSolver,mziSolver,...
        plotResolution,randomSeed,trial);
    result.completed = true;
    result.success = mod(trial,7)~=2;
    result.rawSincReference = [.4 .1];
    result.referenceResult = struct('metrics',struct('functionEvaluations',10+trial));
    result.mziResult = struct('metrics',struct('functionEvaluations',20+trial),...
        'realizedCoefficientMatrix',zeros(4,3));
    result.diagnosticPayload = complex([trial trial+1],[trial+2 trial+3]);
end
