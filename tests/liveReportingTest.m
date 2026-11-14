classdef liveReportingTest < matlab.unittest.TestCase
    properties (TestParameter)
        solverIndex = struct('ga',0,'particleswarm',1,'surrogateopt',2,...
            'simulannealbnd',3,'patternsearch',4,'paretosearch',5);
    end
    methods (TestClassSetup)
        function paths(testCase)
            folder = fileparts(mfilename('fullpath'));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fileparts(folder)));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(folder));
        end
    end
    methods (Test)
        function everySolverCanSerializeItsDiagnostics(testCase,solverIndex)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            mkdir(fullfile(folder.Folder,'trials'));
            mkdir(fullfile(folder.Folder,'workers'));
            reporter = fpf.TrialReporter(folder.Folder,1,[4 .2 0 solverIndex solverIndex 1]);
            originalRandomState = rng;
            testCase.addTeardown(@() rng(originalRandomState));
            fpf.currentReporter(reporter);
            testCase.addTeardown(@() fpf.currentReporter([]));

            [~,~,flag,output,name] = fpf.runGlobalSolver(@(~) 0,[0 -1],[1 1],...
                [.5 .5],solverIndex,"reference",Display="off");
            reporter.finish(struct('success',true,'exitFlag',flag,'output',output,'solverName',name),0);
            record = liveReportingTest.records(folder.Folder);

            testCase.verifyEqual(record.result.solverName,char(name));
            testCase.verifyEqual(record.result.exitFlag,flag);
            testCase.verifyTrue(isstruct(record.result.output));
        end
        function completedTrialsRetainAllOutcomesAndScientificData(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            config = liveReportingTest.config();
            baseline = fpf.runSweep(config,1:3,0,RunTrial=@liveReportingTest.trial);

            actual = fpf.runSweep(config,1:3,0,RunTrial=@liveReportingTest.trial,LiveDirectory=folder.Folder);
            records = liveReportingTest.records(folder.Folder);
            worker = liveReportingTest.worker(folder.Folder);

            testCase.verifyEqual(actual,baseline);
            testCase.verifyEqual([records.global_trial_id],[1 2 3]);
            testCase.verifyEqual(string({records.status}),["succeeded" "nonconverged" "failed"]);
            testCase.verifyEqual(records(1).result.mziResult.design.real,[1;2],AbsTol=0);
            testCase.verifyEqual(records(1).result.mziResult.design.imag,[3;4],AbsTol=0);
            testCase.verifyEqual(records(1).result.mziResult.design.size,[1;2]);
            testCase.verifyEqual(records(3).result.failureIdentifier,'fixture:Failed');
            testCase.verifyFalse(worker.active);
            testCase.verifyEmpty(fpf.currentReporter());
        end

        function objectiveTrackingPreservesSolverOutputAndCounts(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            mkdir(fullfile(folder.Folder,'trials'));
            mkdir(fullfile(folder.Folder,'workers'));
            objective = @(x) sum((x-0.5).^2);
            [baseline,value,flag,output] = fpf.runGlobalSolver(objective,[0 0],[1 1],[0.1 0.1],4,"reference",Display="off");
            reporter = fpf.TrialReporter(folder.Folder,1,[4 .2 0 4 4 1]);
            fpf.currentReporter(reporter);
            testCase.addTeardown(@() fpf.currentReporter([]));

            [actual,actualValue,actualFlag,actualOutput] = fpf.runGlobalSolver(objective,[0 0],[1 1],[0.1 0.1],4,"reference",Display="off");
            reporter.finish(struct('success',true),actualValue);
            worker = liveReportingTest.worker(folder.Folder);

            testCase.verifyEqual(actual,baseline,AbsTol=1e-12);
            testCase.verifyEqual(actualValue,value,AbsTol=1e-12);
            testCase.verifyEqual(actualFlag,flag);
            testCase.verifyEqual(actualOutput.funccount,output.funccount);
            testCase.verifyEqual(worker.objective_evaluations,actualOutput.funccount);
        end

        function unexpectedExceptionsPublishFailureAndStillFailSweep(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            config = liveReportingTest.config();

            testCase.verifyError(@() fpf.runSweep(config,1,0,...
                RunTrial=@liveReportingTest.throwingTrial,LiveDirectory=folder.Folder),'fixture:Unexpected');
            records = liveReportingTest.records(folder.Folder);

            testCase.verifyEqual(records.status,'failed');
            testCase.verifyEqual(records.result.failureIdentifier,'fixture:Unexpected');
            testCase.verifyEmpty(fpf.currentReporter());
        end

        function realTwoStageTrialPreservesNumericalResults(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            config = liveReportingTest.config();
            config.N_tr = 1;
            baseline = fpf.run(4,.2,4,4,10001,0,SaveArtifacts=false,...
                Display="off",Verbose=false,CollectDiagnostics=false,ThrowOnFailure=false);

            fpf.runSweep(config,1,0,LiveDirectory=folder.Folder);
            record = liveReportingTest.records(folder.Folder);

            testCase.verifyEqual(record.result.success,baseline.success);
            testCase.verifyEqual(record.result.referenceResult.objectiveValue,...
                baseline.referenceResult.objectiveValue,AbsTol=1e-12);
            testCase.verifyEqual(record.result.mziResult.objectiveValue,...
                baseline.mziResult.objectiveValue,AbsTol=1e-12);
            testCase.verifyEqual(record.result.referenceResult.metrics.functionEvaluations,...
                baseline.referenceResult.metrics.functionEvaluations);
            testCase.verifyEqual(record.result.mziResult.metrics.functionEvaluations,...
                baseline.mziResult.metrics.functionEvaluations);
            testCase.verifyGreaterThan(record.elapsed_seconds,0);
        end

        function processWorkersWriteEveryTrialExactlyOnce(testCase)
            testCase.assumeTrue(license('test','Distrib_Computing_Toolbox') ~= 0);
            testCase.assumeEmpty(gcp('nocreate'));
            testCase.addTeardown(@liveReportingTest.closePool);
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            config = liveReportingTest.config();
            config.N_tr = 8;
            baseline = fpf.runSweep(config,1:8,0,RunTrial=@liveReportingTest.trial);

            actual = fpf.runSweep(config,8:-1:1,2,RunTrial=@liveReportingTest.trial,LiveDirectory=folder.Folder);
            records = liveReportingTest.records(folder.Folder);

            testCase.verifyEqual([records.global_trial_id],1:8);
            testCase.verifyEqual(actual.success,flipud(baseline.success));
            testCase.verifyEqual(actual.errors,flipud(baseline.errors),AbsTol=0);
            testCase.verifyEqual(actual.evaluations,flipud(baseline.evaluations),AbsTol=0);
            testCase.verifyNumElements(dir(fullfile(folder.Folder,'workers','worker_*.json')),2);
        end
    end
    methods (Static)
        function result = trial(fir,passband,reference,mzi,~,seed,varargin)
            parser = inputParser;
            parser.KeepUnmatched = true;
            addParameter(parser,'TrialIndex',1);
            parse(parser,varargin{:});
            index = parser.Results.TrialIndex;
            result = fpf.initializeRunResult(fir,passband,reference,mzi,10001,seed,index);
            result.success = mod(index,3) == 1;
            result.completed = mod(index,3) ~= 0;
            result.rawSincReference = [.5 0];
            result.referenceResult = struct('x',[.5 0],...
                'metrics',struct('functionEvaluations',10));
            result.mziResult = struct('realizedCoefficientMatrix',...
                [[.6;.5;.5;.5],zeros(4,2)],'design',[1+3i 2+4i],...
                'metrics',struct('functionEvaluations',20));
            if mod(index,3) == 0
                result.failureIdentifier = 'fixture:Failed';
                result.failureMessage = 'Synthetic trial failure';
                result.failureStage = 'mzi';
            end
        end
    end
    methods (Static, Access = private)
        function config = config()
            config = fpf.benchmarkConfig();
            config.firOrders = 4;
            config.passbandRatios = .2;
            config.randomSeeds = 0;
            config.referenceSolvers = 4;
            config.mziSolvers = 4;
            config.N_tr = 3;
        end
        function records = records(folder)
            files = dir(fullfile(folder,'trials','trial_*.json'));
            cells = arrayfun(@(file) jsondecode(fileread(fullfile(file.folder,file.name))),files,UniformOutput=false);
            records = vertcat(cells{:}).';
        end
        function result = worker(folder)
            files = dir(fullfile(folder,'workers','worker_*.json'));
            result = jsondecode(fileread(fullfile(files(1).folder,files(1).name)));
        end
        function result = throwingTrial(varargin) %#ok<STOUT>
            error('fixture:Unexpected','Synthetic unexpected exception');
        end
        function closePool()
            pool = gcp('nocreate');
            if ~isempty(pool)
                delete(pool);
            end
        end
    end
end
