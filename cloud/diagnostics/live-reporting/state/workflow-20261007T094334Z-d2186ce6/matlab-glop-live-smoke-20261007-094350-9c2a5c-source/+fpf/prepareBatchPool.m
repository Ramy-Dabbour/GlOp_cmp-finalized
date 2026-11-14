function workerCount = prepareBatchPool(workerCount)
%PREPAREBATCHPOOL Start exactly one single-threaded process worker per vCPU.
%   Batch allocates the VM; this pool distributes that task's global trials.
%   Change only this session's cluster object, never the saved user profile.
    arguments
        workerCount (1,1) double {mustBeReal,mustBeFinite,mustBeInteger,mustBePositive}
    end
    pool = gcp("nocreate");
    if isempty(pool)
        cluster = parcluster("Processes");
        cluster.NumWorkers = workerCount;
        cluster.NumThreads = 1;
        pool = parpool(cluster,workerCount);
    end
    if isa(pool,"parallel.ThreadPool") || pool.NumWorkers ~= workerCount || ...
            pool.Cluster.NumThreads ~= 1
        error("fpf:BatchPoolMismatch",...
            "Batch requires exactly %d process workers with one computational thread each.",...
            workerCount);
    end
    fprintf("Batch pool: %d process workers, one computational thread per worker.\n",...
        pool.NumWorkers);
end
