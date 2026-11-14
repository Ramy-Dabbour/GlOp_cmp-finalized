function benchmarkResults = runCloudCheckpointSmoke(taskRoot,taskIndex,taskCount,identity,options)
%RUNCLOUDCHECKPOINTSMOKE Exercise eight workers, durability, and recovery.
% Use a separate smoke run URI/manifest. First attempt: InterruptAfterCommits=3;
% resume the identical manifest/run URI with InterruptAfterCommits=Inf.
% Deliberate interruption raises fpf:SimulatedCloudInterruption after snapshots.
    arguments
        taskRoot (1,1) string
        taskIndex (1,1) double
        taskCount (1,1) double
        identity (1,1) struct
        options.InterruptAfterCommits (1,1) double = Inf
        options.HardCrashAfterCommits (1,1) double = Inf
    end
    config = fpf.benchmarkConfig();
    config.firOrders = 4;
    config.passbandRatios = .2;
    config.randomSeeds = 0;
    config.referenceSolvers = 0;
    config.mziSolvers = 1;
    config.N_tr = 24;
    config.N_s = 21;
    benchmarkResults = fpf.runCloudCheckpointShard(taskRoot,taskIndex,taskCount,identity,...
        Config=config,RunTrial=@fpf.cloudCheckpointSmokeTrial,RequestedWorkers=8,...
        AckPollSeconds=.2,HeartbeatSeconds=2,InterruptAfterCommits=options.InterruptAfterCommits,...
        HardCrashAfterCommits=options.HardCrashAfterCommits);
end
