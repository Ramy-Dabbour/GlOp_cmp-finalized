classdef checkpointRecoveryFixture
    % Small, deliberately slow fixture for killing external MATLAB processes.
    methods (Static)
        function run(outputDirectory)
            config = fpf.benchmarkConfig();
            config.firOrders = 4;
            config.passbandRatios = 0.2;
            config.randomSeeds = 0;
            config.referenceSolvers = 0;
            config.mziSolvers = 1;
            config.N_tr = 8;
            config.N_s = 21;
            runTrial = @(varargin) checkpointRecoveryFixture.trial(outputDirectory,varargin{:});
            actual = fpf.runLocalBenchmark(Config=config,RequestedWorkers=2,...
                OutputDirectory=outputDirectory,RunTrial=runTrial,HeartbeatSeconds=3);
            saved = load(fullfile(outputDirectory,'benchmark_results.mat'));
            if ~saved.progress.is_complete, return; end
            expected = fpf.runSweep(config,1:8,0,RunTrial=@parallelSweepTest.seededTrial);
            assert(isequaln(actual,fpf.summarizeSweep(expected)),'fixture:WrongResult','Resumed result differs from oracle.');
            results = runtests('tests/localCheckpointTest.m',Tag='Unit');
            assertSuccess(results);
            results = runtests('tests/parallelSweepTest.m',Tag='Unit');
            assertSuccess(results);
            fprintf('EXTERNAL_RECOVERY_FIXTURE_PASSED\n');
        end
        function result = trial(outputDirectory,varargin)
            parser = inputParser;
            parser.KeepUnmatched = true;
            addParameter(parser,'TrialIndex',1);
            parse(parser,varargin{7:end});
            id = parser.Results.TrialIndex;
            file = fopen(fullfile(outputDirectory,sprintf('calls_%03d.txt',id)),'a');
            assert(file>=0);
            cleanup = onCleanup(@() fclose(file));
            fprintf(file,'%s\n',fpf.TrialReporter.utcNow());
            clear cleanup
            reporter = fpf.currentReporter();
            reporter.stage('reference');
            for step = 1:200
                pause(0.1);
                reporter.evaluated(1/step);
            end
            result = parallelSweepTest.seededTrial(varargin{:});
        end
    end
end
