cd('C:/Users/Dell/Documents/MATLAB/GlOp_cmp');
fprintf('MATLAB version: %s\n', version);
disp(parallel.listProfiles);
parallel.defaultProfile('Processes');
assert(string(parallel.defaultProfile()) == "Processes");
cluster = parcluster('Processes');
assert(string(cluster.Type) == "Local");
fprintf('LOCAL_PROFILE: %s; type=%s; workers=%d; threads=%d\n', ...
    parallel.defaultProfile(), string(cluster.Type), cluster.NumWorkers, cluster.NumThreads);
assert(license('test','Distrib_Computing_Toolbox') ~= 0);
assert(license('test','Optimization_Toolbox') ~= 0);
assert(license('test','GADS_Toolbox') ~= 0);
parallel.validateProfile('Processes', StagesToRun="parcluster", ...
    NumWorkersToUse=2, ...
    ReportFile='C:/Users/Dell/Documents/MATLAB/GlOp_cmp/local-runs/20261011-125746/profile-validation.txt');
suite = testsuite('tests/parallelSweepTest.m');
suite = suite(contains(string({suite.Name}), "processPoolMatchesSerialWithSeededTrials"));
assert(numel(suite) == 1);
results = run(suite);
assertSuccess(results);
fprintf('LOCAL_PREFLIGHT_PASSED\n');
