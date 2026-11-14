classdef parallelSweepTest < matlab.unittest.TestCase
    % Regression coverage for the flattened trial space and Batch reduction.

    properties (TestParameter)
        invalidCoverage = struct('missing', "missing", ...
            'duplicate', "duplicate");
        invalidShards = struct('missing', "missing", ...
            'duplicateTask', "duplicateTask", ...
            'configuration', "configuration", ...
            'taskCount', "taskCount");
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
        function mapsEveryTrialInOriginalLoopOrder(testCase)
            config = parallelSweepTest.smallConfig();
            [expectedParameters,expectedPairs] = ...
                parallelSweepTest.originalLoopParameters(config);

            shape = fpf.sweepSize(config);
            [parameters,pairIndices] = fpf.trialParameters( ...
                config,1:prod(shape));

            testCase.verifyEqual(shape,[3 2 2 2 2 2]);
            testCase.verifyEqual(parameters,expectedParameters,AbsTol=0);
            testCase.verifyEqual(pairIndices,expectedPairs);
            testCase.verifyEqual(size(unique(parameters,'rows'),1),prod(shape));
        end

        function mapsReorderedSubsetAcrossDimensionBoundaries(testCase)
            config = parallelSweepTest.smallConfig();
            [allParameters,allPairs] = ...
                parallelSweepTest.originalLoopParameters(config);
            indices = [96 1 3 4 6 7 12 13 24 25 48 49];

            [parameters,pairIndices] = fpf.trialParameters(config,indices);

            testCase.verifyEqual(parameters,allParameters(indices,:),AbsTol=0);
            testCase.verifyEqual(pairIndices,allPairs(indices));
        end

        function fiveThousandBatchTasksCoverDefaultSweepExactlyOnce(testCase)
            config = fpf.benchmarkConfig();
            totalTests = prod(fpf.sweepSize(config));

            partitions = parallelSweepTest.partitionWork(totalTests,5000);
            assignedIndices = vertcat(partitions{:});
            partitionSizes = cellfun(@numel,partitions);

            testCase.verifyEqual(totalTests,77760);
            testCase.verifyEqual(sort(assignedIndices),(1:totalTests).');
            testCase.verifyLessThanOrEqual(max(partitionSizes)-min(partitionSizes),1);
            testCase.verifyEqual(partitions{1},(1:5000:totalTests).');
            testCase.verifyEqual(partitions{5000},(5000:5000:totalTests).');
            testCase.verifyEmpty(fpf.batchWorkIndices(2,4999,5000));
        end

        function serialSweepMatchesIndependentNestedLoopOracle(testCase)
            config = parallelSweepTest.smallConfig();
            [parameters,~] = parallelSweepTest.originalLoopParameters(config);
            indices = [size(parameters,1):-2:1, size(parameters,1)-1:-2:1];
            expected = parallelSweepTest.runOriginalTrials(config,parameters);

            actual = fpf.runSweep(config,indices,0, ...
                RunTrial=@parallelSweepTest.seededTrial);

            testCase.verifyEqual(actual.config,config);
            testCase.verifyEqual(actual.workIndices,indices.');
            testCase.verifyEqual(actual.success,expected.success(indices));
            testCase.verifyEqual(actual.errors,expected.errors(indices),AbsTol=0);
            testCase.verifyEqual(actual.evaluations, ...
                expected.evaluations(indices),AbsTol=0);
        end

        function sweepRejectsDuplicateGlobalTrials(testCase)
            config = parallelSweepTest.smallConfig();

            testCase.verifyError(@() fpf.runSweep(config,[1 2 1],0, ...
                RunTrial=@parallelSweepTest.seededTrial),'fpf:DuplicateTrial');
        end

        function emptyBatchAssignmentProducesEmptyResultColumns(testCase)
            config = parallelSweepTest.smallConfig();

            actual = fpf.runSweep(config,[],0, ...
                RunTrial=@parallelSweepTest.seededTrial);

            testCase.verifyEqual(actual.config,config);
            testCase.verifySize(actual.workIndices,[0 1]);
            testCase.verifySize(actual.success,[0 1]);
            testCase.verifySize(actual.errors,[0 1]);
            testCase.verifySize(actual.evaluations,[0 1]);
        end

        function failedTrialsStayInDenominatorAndContributeNoMetrics(testCase)
            config = parallelSweepTest.smallConfig();
            trials = parallelSweepTest.syntheticResults(config);
            trials.success(:) = false;
            trials.errors(:) = 0;
            trials.evaluations(:) = 0;
            trials.success(1) = true;
            trials.errors(1) = 0.25;
            trials.evaluations(1) = 10;
            trialsPerPair = config.N_tr*numel(config.firOrders)* ...
                numel(config.passbandRatios)*numel(config.randomSeeds);

            actual = fpf.summarizeSweep(trials);

            testCase.verifyEqual(actual.favorabilityIndex, ...
                [1/trialsPerPair/0.25/log(10);0;0;0],AbsTol=1e-15);
            testCase.verifyEqual(actual.referenceSolver, ...
                ["ga";"simulannealbnd";"ga";"simulannealbnd"]);
            testCase.verifyEqual(actual.mziSolver, ...
                ["particleswarm";"particleswarm";"patternsearch";"patternsearch"]);
        end

        function summaryMatchesOriginalGroupedFloatingPointSums(testCase)
            config = parallelSweepTest.smallConfig();
            trials = parallelSweepTest.syntheticResults(config);
            trials.success(:) = true;
            trials.errors(:) = 1;
            trials.errors(1) = 1e16;
            trials.evaluations(:) = 3;
            expected = parallelSweepTest.originalSummary(trials);
            shuffled = parallelSweepTest.selectTrials(trials, ...
                numel(trials.workIndices):-1:1);

            actual = fpf.summarizeSweep(shuffled);

            testCase.verifyEqual(actual.favorabilityIndex,expected, ...
                RelTol=1e-14,AbsTol=0);
        end

        function summaryRejectsIncompleteOrDuplicateWork(testCase,invalidCoverage)
            trials = parallelSweepTest.syntheticResults( ...
                parallelSweepTest.smallConfig());
            malformed = parallelSweepTest.breakCoverage(trials,invalidCoverage);

            testCase.verifyError(@() fpf.summarizeSweep(malformed), ...
                'fpf:IncompleteSweep');
        end

        function mergesInterleavedShardsAndWritesMatchingMatAndCsv(testCase)
            folder = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            config = parallelSweepTest.smallConfig();
            trials = parallelSweepTest.syntheticResults(config);
            expected = fpf.summarizeSweep(trials);
            parallelSweepTest.writeShards(folder.Folder,trials,3);
            outputPath = fullfile(folder.Folder,'merged.mat');

            actual = fpf.mergeBatchResults(folder.Folder,outputPath);
            saved = load(outputPath,'benchmarkResults');
            csv = readtable(fullfile(folder.Folder,'merged.csv'),TextType='string');

            testCase.verifyEqual(actual,expected);
            testCase.verifyEqual(saved.benchmarkResults,expected);
            testCase.verifyEqual(csv.referenceSolver,expected.referenceSolver);
            testCase.verifyEqual(csv.mziSolver,expected.mziSolver);
            testCase.verifyEqual(csv.favorabilityIndex, ...
                expected.favorabilityIndex,RelTol=1e-12,AbsTol=1e-15);
        end

        function mergeRejectsInvalidShardSets(testCase,invalidShards)
            folder = testCase.applyFixture( ...
                matlab.unittest.fixtures.TemporaryFolderFixture);
            trials = parallelSweepTest.syntheticResults( ...
                parallelSweepTest.smallConfig());
            parallelSweepTest.writeShards(folder.Folder,trials,3);
            expectedError = parallelSweepTest.breakShards( ...
                folder.Folder,invalidShards);

            testCase.verifyError(@() fpf.mergeBatchResults( ...
                folder.Folder,fullfile(folder.Folder,'merged.mat')),expectedError);
        end
    end

    methods (Test, TestTags = {'Integration'})
        function batchPoolUsesEveryAllocatedVcpuWithOneThread(testCase)
            testCase.assumeTrue(license('test','Distrib_Computing_Toolbox') ~= 0);
            originalPool = gcp('nocreate');
            testCase.assumeEmpty(originalPool);
            testCase.addTeardown(@() parallelSweepTest.closeNewPool(originalPool));
            savedCluster = parcluster('Processes');
            originalWorkers = savedCluster.NumWorkers;

            workerCount = fpf.prepareBatchPool(8);
            pool = gcp('nocreate');

            testCase.verifyEqual(workerCount,8);
            testCase.verifyEqual(pool.NumWorkers,8);
            testCase.verifyEqual(pool.Cluster.NumThreads,1);
            unchangedCluster = parcluster('Processes');
            testCase.verifyEqual(unchangedCluster.NumWorkers,originalWorkers);
            testCase.verifyError(@() fpf.prepareBatchPool(7),'fpf:BatchPoolMismatch');
        end

        function processPoolMatchesSerialWithSeededTrials(testCase)
            testCase.assumeTrue(license('test','Distrib_Computing_Toolbox') ~= 0);
            originalPool = gcp('nocreate');
            testCase.addTeardown(@() parallelSweepTest.closeNewPool(originalPool));
            config = parallelSweepTest.smallConfig();
            indices = prod(fpf.sweepSize(config)):-1:1;
            serial = fpf.runSweep(config,indices,0, ...
                RunTrial=@parallelSweepTest.seededTrial);

            parallel = fpf.runSweep(config,indices,2, ...
                RunTrial=@parallelSweepTest.seededTrial);

            testCase.verifyEqual(parallel.workIndices,serial.workIndices);
            testCase.verifyEqual(parallel.success,serial.success);
            testCase.verifyEqual(parallel.errors,serial.errors,AbsTol=0);
            testCase.verifyEqual(parallel.evaluations,serial.evaluations,AbsTol=0);
            testCase.verifyEqual(fpf.summarizeSweep(parallel), ...
                fpf.summarizeSweep(serial));
        end
    end

    methods (Static)
        function result = seededTrial(firOrder,passbandRatio, ...
                referenceSolver,mziSolver,~,randomSeed,varargin)
            parser = inputParser;
            parser.KeepUnmatched = true;
            addParameter(parser,'TrialIndex',1);
            parse(parser,varargin{:});
            trialIndex = parser.Results.TrialIndex;
            previousStream = RandStream.getGlobalStream;
            cleanup = onCleanup(@() RandStream.setGlobalStream(previousStream));
            fpf.seedTrialStage(randomSeed,trialIndex,'reference');
            referenceDraw = rand;
            fpf.seedTrialStage(randomSeed,trialIndex,'mzi');
            mziDraw = rand;
            result.success = mod(trialIndex+randomSeed+referenceSolver+mziSolver,5) ~= 0;
            if ~result.success
                % Failed solver calls need not contain valid stage outputs.
                return
            end
            delta = 0.01*(firOrder+passbandRatio+referenceSolver+mziSolver) + ...
                0.1*referenceDraw + 0.2*mziDraw;
            result.rawSincReference = [0.5 0];
            result.referenceResult.metrics.functionEvaluations = ...
                10+floor(100*referenceDraw);
            result.mziResult.realizedCoefficientMatrix = ...
                [[0.5+delta;0.5;0.5;0.5],zeros(4,2)];
            result.mziResult.metrics.functionEvaluations = ...
                20+floor(100*mziDraw);
        end
    end

    methods (Static, Access = private)
        function config = smallConfig()
            config = fpf.benchmarkConfig();
            config.firOrders = [4 7];
            config.passbandRatios = [0.2 0.4];
            config.randomSeeds = [0 11];
            config.referenceSolvers = [0 3];
            config.mziSolvers = [1 4];
            config.N_tr = 3;
        end

        function [parameters,pairIndices] = originalLoopParameters(config)
            count = config.N_tr*numel(config.mziSolvers)* ...
                numel(config.referenceSolvers)*numel(config.firOrders)* ...
                numel(config.passbandRatios)*numel(config.randomSeeds);
            parameters = zeros(count,6);
            pairIndices = zeros(count,1);
            index = 0;
            % This is the original ndgrid input order and nested traversal.
            for seed = config.randomSeeds
                for passband = config.passbandRatios
                    for fir = config.firOrders
                        for referenceIndex = 1:numel(config.referenceSolvers)
                            for mziIndex = 1:numel(config.mziSolvers)
                                for trial = 1:config.N_tr
                                    index = index+1;
                                    parameters(index,:) = [fir passband seed ...
                                        config.referenceSolvers(referenceIndex) ...
                                        config.mziSolvers(mziIndex) trial];
                                    pairIndices(index) = referenceIndex + ...
                                        (mziIndex-1)*numel(config.referenceSolvers);
                                end
                            end
                        end
                    end
                end
            end
        end

        function partitions = partitionWork(totalTests,taskCount)
            partitions = cell(taskCount,1);
            for index = 0:taskCount-1
                partitions{index+1} = fpf.batchWorkIndices(totalTests,index,taskCount);
            end
        end

        function trials = runOriginalTrials(config,parameters)
            count = size(parameters,1);
            trials.config = config;
            trials.workIndices = (1:count).';
            trials.success = false(count,1);
            trials.errors = zeros(count,1);
            trials.evaluations = zeros(count,1);
            for index = 1:count
                values = parameters(index,:);
                result = parallelSweepTest.seededTrial(values(1),values(2), ...
                    values(4),values(5),config.N_s,values(3),TrialIndex=values(6));
                trials.success(index) = result.success;
                if result.success
                    trials.errors(index) = fpf.endToEndError( ...
                        result.rawSincReference,result.mziResult.realizedCoefficientMatrix);
                    trials.evaluations(index) = ...
                        result.referenceResult.metrics.functionEvaluations + ...
                        result.mziResult.metrics.functionEvaluations;
                end
            end
        end

        function trials = syntheticResults(config)
            [parameters,~] = parallelSweepTest.originalLoopParameters(config);
            trials = parallelSweepTest.runOriginalTrials(config,parameters);
        end

        function expected = originalSummary(trials)
            config = trials.config;
            pairSize = [numel(config.referenceSolvers),numel(config.mziSolvers)];
            successes = zeros(pairSize);
            errors = zeros(pairSize);
            evaluations = zeros(pairSize);
            operatingPointCount = numel(config.firOrders)* ...
                numel(config.passbandRatios)*numel(config.randomSeeds);
            offset = 0;
            for operatingPoint = 1:operatingPointCount
                for referenceIndex = 1:pairSize(1)
                    for mziIndex = 1:pairSize(2)
                        indices = offset+(1:config.N_tr);
                        successes(referenceIndex,mziIndex) = ...
                            successes(referenceIndex,mziIndex)+sum(trials.success(indices));
                        errors(referenceIndex,mziIndex) = ...
                            errors(referenceIndex,mziIndex)+sum(trials.errors(indices));
                        evaluations(referenceIndex,mziIndex) = ...
                            evaluations(referenceIndex,mziIndex)+sum(trials.evaluations(indices));
                        offset = offset+config.N_tr;
                    end
                end
            end
            means = errors./successes;
            costs = evaluations./successes;
            rates = successes/(operatingPointCount*config.N_tr);
            expected = rates./means./log(costs);
            expected(successes==0) = 0;
            expected = expected(:);
        end

        function selected = selectTrials(trials,indices)
            selected = trials;
            selected.workIndices = trials.workIndices(indices);
            selected.success = trials.success(indices);
            selected.errors = trials.errors(indices);
            selected.evaluations = trials.evaluations(indices);
        end

        function trials = breakCoverage(trials,kind)
            switch kind
                case "missing"
                    trials = parallelSweepTest.selectTrials(trials, ...
                        1:numel(trials.workIndices)-1);
                case "duplicate"
                    trials.workIndices(end) = trials.workIndices(1);
            end
        end

        function writeShards(folder,trials,taskCount)
            totalTests = numel(trials.workIndices);
            for taskIndex = taskCount-1:-1:0
                indices = fpf.batchWorkIndices(totalTests,taskIndex,taskCount);
                trialResults = parallelSweepTest.selectTrials(trials,indices);
                trialResults.taskIndex = taskIndex;
                trialResults.taskCount = taskCount;
                save(fullfile(folder,sprintf('trial_shard_%05d.mat',taskIndex)), ...
                    'trialResults');
            end
        end

        function expectedError = breakShards(folder,kind)
            shardPath = fullfile(folder,'trial_shard_00002.mat');
            saved = load(shardPath,'trialResults');
            trialResults = saved.trialResults;
            switch kind
                case "missing"
                    delete(shardPath);
                    expectedError = 'fpf:IncompleteSweep';
                    return
                case "duplicateTask"
                    trialResults.taskIndex = 0;
                    expectedError = 'fpf:IncompleteSweep';
                case "configuration"
                    trialResults.config.N_s = trialResults.config.N_s+2;
                    expectedError = 'fpf:InconsistentBatchResults';
                case "taskCount"
                    trialResults.taskCount = trialResults.taskCount+1;
                    expectedError = 'fpf:InconsistentBatchResults';
            end
            save(shardPath,'trialResults');
        end

        function closeNewPool(originalPool)
            currentPool = gcp('nocreate');
            if isempty(originalPool) && ~isempty(currentPool)
                delete(currentPool);
            end
        end
    end
end
