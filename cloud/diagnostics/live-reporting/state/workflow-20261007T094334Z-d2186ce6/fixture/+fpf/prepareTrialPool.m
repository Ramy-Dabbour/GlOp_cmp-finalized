function workerLimit = prepareTrialPool(requestedWorkers)
%PREPARETRIALPOOL Reuse or start process workers for independent solver trials.
%   Zero selects client-side execution without starting or changing a pool.
%   Process workers isolate solver state and the surrogate stopping callback.
%   An existing pool is left open; no user-owned pool is deleted or resized.
%   Uses the selected default cluster profile, including remote clusters.
%   Batch initializes an explicit local pool with prepareBatchPool first.

    arguments
        requestedWorkers (1,1) double {mustBeReal,mustBeFinite,mustBeInteger,mustBeNonnegative}
    end

    workerLimit = requestedWorkers;
    if workerLimit == 0
        return
    end
    pool = gcp("nocreate");
    if isempty(pool)
        cluster = parcluster;
        workerLimit = min(workerLimit,cluster.NumWorkers);
        pool = parpool(cluster,workerLimit);
    elseif isa(pool,"parallel.ThreadPool")
        error("fpf:ProcessPoolRequired",...
            "Trial execution uses process workers to isolate solver state. " + ...
            "Close the existing thread pool before running, or set maxTrialWorkers = 0.");
    end
    workerLimit = min(workerLimit,pool.NumWorkers);
    if workerLimit < requestedWorkers
        warning("fpf:WorkerLimitReduced",...
            "Requested up to %d workers; using %d from the selected pool/profile. " + ...
            "Cloud VM allocation is configured separately in matlab-cloud.json.",...
            requestedWorkers,workerLimit);
    end
end
