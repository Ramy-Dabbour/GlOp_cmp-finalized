classdef localCheckpointTest < matlab.unittest.TestCase
    % Exercise durable local results through the public runner interface.

    properties (TestParameter)
        corruption = struct('unreadableFile',"unreadableFile", ...
            'incorrectTrialId',"incorrectTrialId");
    end

    methods (TestClassSetup)
        function addProjectPaths(testCase)
            testFolder = fileparts(mfilename('fullpath'));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture( ...
                fileparts(testFolder)));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture( ...
                testFolder));
        end
    end

    methods (Test, TestTags = {'Unit'})
        function publishesEveryTrialBeforeStartingTheNext(testCase)
            folder = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            config = localCheckpointTest.smallConfig();
            outputDirectory = folder.Folder;
            runTrial = @(varargin) localCheckpointTest.trial( ...
                outputDirectory,true,varargin{:});
            expected = localCheckpointTest.oracle(config);

            actual = fpf.runLocalBenchmark(Config=config,RequestedWorkers=0, ...
                OutputDirectory=folder.Folder,RunTrial=runTrial,HeartbeatSeconds=1);
            saved = load(fullfile(folder.Folder,'benchmark_results.mat'));
            csv = readtable(fullfile(folder.Folder,'benchmark_results.csv'), ...
                TextType='string');
            record = load(localCheckpointTest.checkpointPath(folder.Folder,4));

            testCase.verifyEqual(actual,fpf.summarizeSweep(expected));
            testCase.verifyEqual(saved.benchmarkResults,actual);
            testCase.verifyEqual(csv.referenceSolver,actual.referenceSolver);
            testCase.verifyEqual(csv.mziSolver,actual.mziSolver);
            testCase.verifyEqual(csv.favorabilityIndex,actual.favorabilityIndex, ...
                RelTol=1e-12,AbsTol=1e-15);
            testCase.verifyTrue(all(saved.trialResults.completed));
            testCase.verifyTrue(saved.progress.is_complete);
            testCase.verifyEqual(saved.progress.completed_trials,5);
            testCase.verifyEqual(saved.progress.successful_trials,4);
            testCase.verifyEqual(saved.progress.failed_trials,1);
            testCase.verifyFalse(record.checkpoint.success);
            testCase.verifyEqual(record.checkpoint.result.diagnosticPayload, ...
                complex([4 5],[6 7]),AbsTol=0);
            testCase.verifyEqual(localCheckpointTest.callCounts(folder.Folder), ...
                ones(5,1));
        end

        function interruptionKeepsPartialOutputsAndResumeSkipsCommittedTrials(testCase)
            folder = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            config = localCheckpointTest.smallConfig();
            outputDirectory = folder.Folder;
            runTrial = @(varargin) localCheckpointTest.trial( ...
                outputDirectory,true,varargin{:});
            localCheckpointTest.armFailure(folder.Folder,3);
            expected = localCheckpointTest.oracle(config);

            testCase.verifyError(@() fpf.runLocalBenchmark(Config=config, ...
                RequestedWorkers=0,OutputDirectory=folder.Folder, ...
                RunTrial=runTrial,HeartbeatSeconds=1),'fixture:Interrupted');
            partial = load(fullfile(folder.Folder,'benchmark_results.mat'));
            partialCsv = readtable(fullfile(folder.Folder,'benchmark_results.csv'), ...
                TextType='string');

            testCase.verifyEqual(partial.trialResults.completed, ...
                [true;true;false;false;false]);
            testCase.verifyEqual(partial.trialResults.success(1:2), ...
                expected.success(1:2));
            testCase.verifyEqual(partial.trialResults.errors(1:2), ...
                expected.errors(1:2),AbsTol=0);
            testCase.verifyEqual(partial.progress.completed_trials,2);
            testCase.verifyFalse(partial.progress.is_complete);
            testCase.verifyEqual(partialCsv.favorabilityIndex, ...
                partial.benchmarkResults.favorabilityIndex, ...
                RelTol=1e-12,AbsTol=1e-15);
            testCase.verifyEqual(numel(dir(fullfile(folder.Folder, ...
                'local-results','checkpoints','trial_*.mat'))),2);
            testCase.verifyFalse(isfile( ...
                localCheckpointTest.checkpointPath(folder.Folder,3)));
            testCase.verifyEqual(localCheckpointTest.callCounts(folder.Folder), ...
                [1;1;1;0;0]);

            actual = fpf.runLocalBenchmark(Config=config,RequestedWorkers=0, ...
                OutputDirectory=folder.Folder,RunTrial=runTrial,HeartbeatSeconds=1);
            saved = load(fullfile(folder.Folder,'benchmark_results.mat'));
            csv = readtable(fullfile(folder.Folder,'benchmark_results.csv'), ...
                TextType='string');

            testCase.verifyEqual(actual,fpf.summarizeSweep(expected));
            testCase.verifyEqual(saved.trialResults.success,expected.success);
            testCase.verifyEqual(saved.trialResults.errors,expected.errors,AbsTol=0);
            testCase.verifyEqual(saved.trialResults.evaluations, ...
                expected.evaluations,AbsTol=0);
            testCase.verifyTrue(all(saved.trialResults.completed));
            testCase.verifyTrue(saved.progress.is_complete);
            testCase.verifyEqual(csv.favorabilityIndex,actual.favorabilityIndex, ...
                RelTol=1e-12,AbsTol=1e-15);
            testCase.verifyEqual(localCheckpointTest.callCounts(folder.Folder), ...
                [1;1;2;1;1]);
        end

        function changedConfigurationCannotReuseCheckpoints(testCase)
            folder = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            config = localCheckpointTest.smallConfig();
            outputDirectory = folder.Folder;
            runTrial = @(varargin) localCheckpointTest.trial( ...
                outputDirectory,true,varargin{:});
            fpf.runLocalBenchmark(Config=config,RequestedWorkers=0, ...
                OutputDirectory=folder.Folder,RunTrial=runTrial,HeartbeatSeconds=1);
            changedConfig = config;
            changedConfig.N_s = config.N_s+2;
            before = load(fullfile(folder.Folder,'benchmark_results.mat'));

            testCase.verifyError(@() fpf.runLocalBenchmark(Config=changedConfig, ...
                RequestedWorkers=0,OutputDirectory=folder.Folder, ...
                RunTrial=runTrial,HeartbeatSeconds=1),'fpf:CheckpointMismatch');
            after = load(fullfile(folder.Folder,'benchmark_results.mat'));

            testCase.verifyEqual(after,before);
            testCase.verifyEqual(localCheckpointTest.callCounts(folder.Folder), ...
                ones(5,1));
        end

        function corruptedCheckpointStopsBeforeAnotherTrial(testCase,corruption)
            folder = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            config = localCheckpointTest.smallConfig();
            outputDirectory = folder.Folder;
            runTrial = @(varargin) localCheckpointTest.trial( ...
                outputDirectory,true,varargin{:});
            fpf.runLocalBenchmark(Config=config,RequestedWorkers=0, ...
                OutputDirectory=folder.Folder,RunTrial=runTrial,HeartbeatSeconds=1);
            localCheckpointTest.corruptCheckpoint(folder.Folder,2,corruption);
            before = load(fullfile(folder.Folder,'benchmark_results.mat'));

            testCase.verifyError(@() fpf.runLocalBenchmark(Config=config, ...
                RequestedWorkers=0,OutputDirectory=folder.Folder, ...
                RunTrial=runTrial,HeartbeatSeconds=1),'fpf:CorruptCheckpoint');
            after = load(fullfile(folder.Folder,'benchmark_results.mat'));

            testCase.verifyEqual(after,before);
            testCase.verifyEqual(localCheckpointTest.callCounts(folder.Folder), ...
                ones(5,1));
        end

        function committedTrialsRebuildStaleMatAndMissingCsv(testCase)
            folder = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            config = localCheckpointTest.smallConfig();
            outputDirectory = folder.Folder;
            runTrial = @(varargin) localCheckpointTest.trial( ...
                outputDirectory,true,varargin{:});
            localCheckpointTest.armFailure(folder.Folder,3);
            testCase.verifyError(@() fpf.runLocalBenchmark(Config=config, ...
                RequestedWorkers=0,OutputDirectory=folder.Folder, ...
                RunTrial=runTrial,HeartbeatSeconds=1),'fixture:Interrupted');
            matPath = fullfile(folder.Folder,'benchmark_results.mat');
            csvPath = fullfile(folder.Folder,'benchmark_results.csv');
            savedPartialPath = fullfile(folder.Folder,'saved_partial.mat');
            copyfile(matPath,savedPartialPath);
            expected = fpf.runLocalBenchmark(Config=config,RequestedWorkers=0, ...
                OutputDirectory=folder.Folder,RunTrial=runTrial,HeartbeatSeconds=1);
            copyfile(savedPartialPath,matPath,'f');
            delete(csvPath);

            actual = fpf.runLocalBenchmark(Config=config,RequestedWorkers=0, ...
                OutputDirectory=folder.Folder,RunTrial=runTrial,HeartbeatSeconds=1);
            saved = load(matPath);
            csv = readtable(csvPath,TextType='string');

            testCase.verifyEqual(actual,expected);
            testCase.verifyEqual(saved.benchmarkResults,expected);
            testCase.verifyTrue(all(saved.trialResults.completed));
            testCase.verifyTrue(saved.progress.is_complete);
            testCase.verifyEqual(csv.favorabilityIndex,expected.favorabilityIndex, ...
                RelTol=1e-12,AbsTol=1e-15);
            testCase.verifyEqual(localCheckpointTest.callCounts(folder.Folder), ...
                [1;1;2;1;1]);
        end
    end

    methods (Test, TestTags = {'Integration'})
        function localProcessWorkersPersistResultsAndResumeWithoutRepeats(testCase)
            testCase.assumeTrue(license('test','Distrib_Computing_Toolbox') ~= 0);
            originalPool = gcp('nocreate');
            testCase.assumeEmpty(originalPool);
            testCase.addTeardown(@() localCheckpointTest.closeNewPool(originalPool));
            folder = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            config = localCheckpointTest.smallConfig();
            outputDirectory = folder.Folder;
            runTrial = @(varargin) localCheckpointTest.trial( ...
                outputDirectory,false,varargin{:});
            expected = localCheckpointTest.oracle(config);

            actual = fpf.runLocalBenchmark(Config=config,RequestedWorkers=2, ...
                OutputDirectory=folder.Folder,RunTrial=runTrial,HeartbeatSeconds=1);
            resumed = fpf.runLocalBenchmark(Config=config,RequestedWorkers=2, ...
                OutputDirectory=folder.Folder,RunTrial=runTrial,HeartbeatSeconds=1);
            saved = load(fullfile(folder.Folder,'benchmark_results.mat'));

            testCase.verifyEqual(actual,fpf.summarizeSweep(expected));
            testCase.verifyEqual(resumed,actual);
            testCase.verifyTrue(all(saved.trialResults.completed));
            testCase.verifyTrue(saved.progress.is_complete);
            testCase.verifyEqual(localCheckpointTest.callCounts(folder.Folder), ...
                ones(5,1));
            testCase.verifyEqual(numel(dir(fullfile(folder.Folder, ...
                'local-results','checkpoints','trial_*.mat'))),5);
        end
    end

    methods (Static)
        function result = trial(outputDirectory,verifyPublished,varargin)
            parser = inputParser;
            parser.KeepUnmatched = true;
            addParameter(parser,'TrialIndex',1);
            parse(parser,varargin{7:end});
            trialId = parser.Results.TrialIndex;
            callPath = fullfile(outputDirectory,sprintf('calls_%03d.txt',trialId));
            file = fopen(callPath,'a');
            assert(file ~= -1,'fixture:CannotRecordCall','Cannot record the trial call.');
            cleanup = onCleanup(@() fclose(file));
            fprintf(file,'%d\n',trialId);
            clear cleanup
            if verifyPublished && trialId > 1
                previousPath = localCheckpointTest.checkpointPath( ...
                    outputDirectory,trialId-1);
                assert(isfile(previousPath),'fixture:MissingCheckpoint', ...
                    'The previous trial must be saved before another trial starts.');
                aggregate = load(fullfile(outputDirectory,'benchmark_results.mat'));
                assert(aggregate.trialResults.completed(trialId-1), ...
                    'fixture:StaleMat','MAT progress must include the previous trial.');
                csv = readtable(fullfile(outputDirectory,'benchmark_results.csv'), ...
                    TextType='string');
                assert(isequal(csv(:,1:2),aggregate.benchmarkResults(:,1:2)), ...
                    'fixture:StaleCsv','CSV and MAT solver pairs must agree.');
                assert(all(abs(csv.favorabilityIndex- ...
                    aggregate.benchmarkResults.favorabilityIndex) <= ...
                    1e-12*max(1,abs(csv.favorabilityIndex))), ...
                    'fixture:StaleCsv','CSV progress must match the MAT snapshot.');
            end
            failurePath = fullfile(outputDirectory,sprintf('fail_once_%03d',trialId));
            if isfile(failurePath)
                delete(failurePath);
                error('fixture:Interrupted','Simulated interruption at trial %d.',trialId);
            end
            result = parallelSweepTest.seededTrial(varargin{:});
            result.completed = true;
            result.diagnosticPayload = complex([trialId trialId+1], ...
                [trialId+2 trialId+3]);
        end
    end

    methods (Static, Access = private)
        function config = smallConfig()
            config = fpf.benchmarkConfig();
            config.firOrders = 4;
            config.passbandRatios = 0.2;
            config.randomSeeds = 0;
            config.referenceSolvers = 0;
            config.mziSolvers = 1;
            config.N_tr = 5;
            config.N_s = 21;
        end

        function expected = oracle(config)
            expected = fpf.runSweep(config,1:5,0, ...
                RunTrial=@parallelSweepTest.seededTrial);
        end

        function path = checkpointPath(folder,trialId)
            path = fullfile(folder,'local-results','checkpoints', ...
                sprintf('trial_%012d.mat',trialId));
        end

        function armFailure(folder,trialId)
            path = fullfile(folder,sprintf('fail_once_%03d',trialId));
            file = fopen(path,'w');
            assert(file ~= -1,'fixture:CannotArmFailure','Cannot write failure trigger.');
            fclose(file);
        end

        function counts = callCounts(folder)
            counts = zeros(5,1);
            for trialId = 1:5
                path = fullfile(folder,sprintf('calls_%03d.txt',trialId));
                if isfile(path)
                    counts(trialId) = numel(sscanf(fileread(path),'%d'));
                end
            end
        end

        function corruptCheckpoint(folder,trialId,kind)
            path = localCheckpointTest.checkpointPath(folder,trialId);
            switch kind
                case "unreadableFile"
                    file = fopen(path,'w');
                    assert(file ~= -1,'fixture:CannotCorrupt','Cannot corrupt checkpoint.');
                    cleanup = onCleanup(@() fclose(file));
                    fprintf(file,'INTERRUPTED INVALID MAT FILE');
                case "incorrectTrialId"
                    saved = load(path,'checkpoint');
                    checkpoint = saved.checkpoint;
                    checkpoint.globalId = trialId+1;
                    save(path,'checkpoint');
            end
        end

        function closeNewPool(originalPool)
            currentPool = gcp('nocreate');
            if isempty(originalPool) && ~isempty(currentPool)
                delete(currentPool);
            end
        end
    end
end
