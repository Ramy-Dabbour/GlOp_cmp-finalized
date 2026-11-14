classdef cloudCheckpointTest < matlab.unittest.TestCase
    % Real MAT commits and synthetic cloud receipts; no scientific solver runs.
    methods (TestClassSetup)
        function useIsolatedSnapshot(testCase)
            folder = fileparts(mfilename('fullpath'));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fileparts(folder)));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(folder));
        end
    end
    methods (Test, TestTags = {'Unit'})
        function allOutcomesPublishAndResumeWithoutRepeating(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            config = cloudCheckpointTest.config();
            identity = cloudCheckpointTest.identity();
            runTrial = @(varargin) cloudCheckpointTest.trial(folder.Folder,true,varargin{:});
            uploader = cloudCheckpointTest.uploader(folder.Folder);
            testCase.addTeardown(@() cloudCheckpointTest.closeUploader(uploader));

            first = fpf.runCloudCheckpointShard(folder.Folder,0,1,identity,Config=config,...
                RunTrial=runTrial,RequestedWorkers=0,AckPollSeconds=0.02,AckTimeoutSeconds=10);
            resumed = fpf.runCloudCheckpointShard(folder.Folder,0,1,identity,Config=config,...
                RunTrial=runTrial,RequestedWorkers=0,AckPollSeconds=0.02,AckTimeoutSeconds=10);
            saved = load(fullfile(folder.Folder,'results','benchmark_results.mat'));
            failed = load(cloudCheckpointTest.path(folder.Folder,3));
            csv = readtable(fullfile(folder.Folder,'results','trial_results.csv'),TextType='string');

            testCase.verifyEqual(first,resumed);
            testCase.verifyTrue(all(saved.trialResults.completed));
            testCase.verifyEqual(saved.trialResults.success,[true;false;false;false;true]);
            testCase.verifyGreaterThan(saved.trialResults.rawErrors(2),0);
            testCase.verifyEqual(saved.trialResults.rawEvaluations(2),20,AbsTol=0);
            testCase.verifyEqual(saved.trialResults.errors(2:4),zeros(3,1),AbsTol=0);
            testCase.verifyEqual(saved.trialResults.evaluations(2:4),zeros(3,1),AbsTol=0);
            testCase.verifyEqual(saved.trialResults.rawEvaluations(4),10,AbsTol=0);
            testCase.verifyTrue(isnan(saved.trialResults.rawErrors(3)));
            testCase.verifyEqual(failed.checkpoint.exception.identifier,'fixture:ScienceFailure');
            testCase.verifyTrue(saved.progress.is_complete);
            testCase.verifyEqual(logical(csv.completed),true(5,1));
            testCase.verifyEqual(cloudCheckpointTest.counts(folder.Folder),ones(5,1));
        end

        function missingAckIsNotCompletionAndResumeUsesOriginalMat(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            config = cloudCheckpointTest.config();
            identity = cloudCheckpointTest.identity();
            runTrial = @(varargin) cloudCheckpointTest.trial(folder.Folder,false,varargin{:});

            testCase.verifyError(@() fpf.runCloudCheckpointShard(folder.Folder,0,5,identity,...
                Config=config,RunTrial=runTrial,RequestedWorkers=0,AckPollSeconds=0.02,...
                AckTimeoutSeconds=0.1),'fpf:CloudAcknowledgementTimeout');
            partial = load(fullfile(folder.Folder,'results','benchmark_results.mat'));
            originalHash = fpf.cloudFileSha256(cloudCheckpointTest.path(folder.Folder,1));
            uploader = cloudCheckpointTest.uploader(folder.Folder);
            testCase.addTeardown(@() cloudCheckpointTest.closeUploader(uploader));
            fpf.runCloudCheckpointShard(folder.Folder,0,5,identity,Config=config,...
                RunTrial=runTrial,RequestedWorkers=0,AckPollSeconds=0.02,AckTimeoutSeconds=10);
            saved = load(fullfile(folder.Folder,'results','benchmark_results.mat'));

            testCase.verifyFalse(any(partial.trialResults.completed));
            testCase.verifyEqual(saved.trialResults.completed,[true;false;false;false;false]);
            testCase.verifyEqual(fpf.cloudFileSha256(cloudCheckpointTest.path(folder.Folder,1)),originalHash);
            testCase.verifyEqual(cloudCheckpointTest.counts(folder.Folder),[1;0;0;0;0]);
        end

        function invalidAckHashFailsLoudly(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            identity = cloudCheckpointTest.identity();
            runTrial = @(varargin) cloudCheckpointTest.trial(folder.Folder,false,varargin{:});
            parameter = [4 .2 0 0 1 1];
            testCase.verifyError(@() fpf.runCloudCheckpointTrial(runTrial,parameter,21,"",1,...
                folder.Folder,identity,AckTimeoutSeconds=0.1,AckPollSeconds=0.02),...
                'fpf:CloudAcknowledgementTimeout');
            ack = identity;
            ack.trial_id = 1;
            ack.sha256 = repmat('0',1,64);
            fpf.writeCloudJson(fullfile(folder.Folder,'results','acks','trial_000000000001.json'),ack);

            testCase.verifyError(@() fpf.runCloudCheckpointTrial(runTrial,parameter,21,"",1,...
                folder.Folder,identity,AckTimeoutSeconds=0.1,AckPollSeconds=0.02),...
                'fpf:InvalidCloudAcknowledgement');
            testCase.verifyEqual(cloudCheckpointTest.counts(folder.Folder),[1;0;0;0;0]);
        end

        function identityMismatchCannotReuseRecords(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            identity = cloudCheckpointTest.identity();
            runTrial = @(varargin) cloudCheckpointTest.trial(folder.Folder,false,varargin{:});
            parameter = [4 .2 0 0 1 1];
            testCase.verifyError(@() fpf.runCloudCheckpointTrial(runTrial,parameter,21,"",1,...
                folder.Folder,identity,AckTimeoutSeconds=0.1,AckPollSeconds=0.02),...
                'fpf:CloudAcknowledgementTimeout');
            identity.source_sha256 = repmat('c',1,64);

            testCase.verifyError(@() fpf.runCloudCheckpointTrial(runTrial,parameter,21,"",1,...
                folder.Folder,identity,AckTimeoutSeconds=0.1,AckPollSeconds=0.02),...
                'fpf:CorruptCheckpoint');
        end

        function stridedAssignmentKeepsUnassignedMaskFalse(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            runTrial = @(varargin) cloudCheckpointTest.trial(folder.Folder,false,varargin{:});
            uploader = cloudCheckpointTest.uploader(folder.Folder);
            testCase.addTeardown(@() cloudCheckpointTest.closeUploader(uploader));

            fpf.runCloudCheckpointShard(folder.Folder,1,2,cloudCheckpointTest.identity(),...
                Config=cloudCheckpointTest.config(),RunTrial=runTrial,RequestedWorkers=0,...
                AckPollSeconds=0.02,AckTimeoutSeconds=10);
            saved = load(fullfile(folder.Folder,'results','benchmark_results.mat'));

            testCase.verifyEqual(saved.trialResults.completed,[false;true;false;true;false]);
            testCase.verifyEqual(saved.trialResults.assigned,saved.trialResults.completed);
            testCase.verifyEqual(saved.progress.completed_trials,2);
            testCase.verifyTrue(saved.progress.is_complete);
        end

        function telemetryFailureDoesNotLoseScientificResult(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            uploader = cloudCheckpointTest.uploader(folder.Folder);
            testCase.addTeardown(@() cloudCheckpointTest.closeUploader(uploader));
            warningState = warning('off','fpf:AdvisoryTelemetryWrite');
            testCase.addTeardown(@() warning(warningState));
            runTrial = @(varargin) cloudCheckpointTest.trial(folder.Folder,false,varargin{:});

            record = fpf.runCloudCheckpointTrial(runTrial,[4 .2 0 0 1 1],21,...
                fullfile(folder.Folder,'missing-parent','live'),1,folder.Folder,...
                cloudCheckpointTest.identity(),AckPollSeconds=0.02,AckTimeoutSeconds=10);

            testCase.verifyTrue(record.success);
            testCase.verifyEqual(record.result.diagnosticPayload,complex([1 2],[3 4]),AbsTol=0);
        end

        function productionRejectsChangedWorkerOrScienceSettings(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.verifyError(@() fpf.runCloudCheckpointShard(folder.Folder,0,1,...
                cloudCheckpointTest.identity(),RequestedWorkers=2),'fpf:ScientificConfigurationChanged');
            testCase.verifyError(@() fpf.runCloudCheckpointShard(folder.Folder,0,1,...
                cloudCheckpointTest.identity(),Config=cloudCheckpointTest.config()),...
                'fpf:ScientificConfigurationChanged');
        end

        function invalidResponseRetainsReturnedScientificPayload(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            mkdir(fullfile(folder.Folder,'live','trials'));
            mkdir(fullfile(folder.Folder,'live','workers'));
            uploader = cloudCheckpointTest.uploader(folder.Folder);
            testCase.addTeardown(@() cloudCheckpointTest.closeUploader(uploader));

            record = fpf.runCloudCheckpointTrial(@cloudCheckpointTest.invalidTrial,...
                [4 .2 0 0 1 1],21,fullfile(folder.Folder,'live'),1,folder.Folder,...
                cloudCheckpointTest.identity(),AckPollSeconds=.02,AckTimeoutSeconds=10);

            testCase.verifyFalse(record.success);
            testCase.verifyTrue(isnan(record.error));
            testCase.verifyEqual(record.evaluations,20,AbsTol=0);
            testCase.verifyEqual(record.result.diagnosticPayload,'full-scientific-result');
            testCase.verifyTrue(all(isnan(record.result.mziResult.realizedCoefficientMatrix),'all'));
            testCase.verifyNotEmpty(record.metricException.message);
        end

        function interruptionAfterThreeCommitsResumesRemainingTrials(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            runTrial = @(varargin) cloudCheckpointTest.trial(folder.Folder,false,varargin{:});
            uploader = cloudCheckpointTest.uploader(folder.Folder);
            testCase.addTeardown(@() cloudCheckpointTest.closeUploader(uploader));
            testCase.verifyError(@() fpf.runCloudCheckpointShard(folder.Folder,0,1,...
                cloudCheckpointTest.identity(),Config=cloudCheckpointTest.config(),...
                RunTrial=runTrial,RequestedWorkers=0,AckPollSeconds=.02,AckTimeoutSeconds=10,...
                InterruptAfterCommits=3),'fpf:SimulatedCloudInterruption');
            partial = load(fullfile(folder.Folder,'results','benchmark_results.mat'));
            originalHash = fpf.cloudFileSha256(cloudCheckpointTest.path(folder.Folder,1));

            fpf.runCloudCheckpointShard(folder.Folder,0,1,cloudCheckpointTest.identity(),...
                Config=cloudCheckpointTest.config(),RunTrial=runTrial,RequestedWorkers=0,...
                AckPollSeconds=.02,AckTimeoutSeconds=10);
            saved = load(fullfile(folder.Folder,'results','benchmark_results.mat'));

            testCase.verifyEqual(partial.trialResults.completed,[true;true;true;false;false]);
            testCase.verifyEqual(partial.progress.status,'failed');
            testCase.verifyTrue(all(saved.trialResults.completed));
            testCase.verifyEqual(cloudCheckpointTest.counts(folder.Folder),ones(5,1));
            testCase.verifyEqual(fpf.cloudFileSha256(cloudCheckpointTest.path(folder.Folder,1)),originalHash);
        end
    end
    methods (Test, TestTags = {'Integration'})
        function processWorkersSaveAllOutcomesAndResume(testCase)
            testCase.assumeEmpty(gcp('nocreate'));
            testCase.addTeardown(@() cloudCheckpointTest.closePool());
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            runTrial = @(varargin) cloudCheckpointTest.trial(folder.Folder,false,varargin{:});
            uploader = cloudCheckpointTest.uploader(folder.Folder);
            testCase.addTeardown(@() cloudCheckpointTest.closeUploader(uploader));

            first = fpf.runCloudCheckpointShard(folder.Folder,0,1,cloudCheckpointTest.identity(),...
                Config=cloudCheckpointTest.config(),RunTrial=runTrial,RequestedWorkers=2,...
                AckPollSeconds=0.02,AckTimeoutSeconds=30);
            resumed = fpf.runCloudCheckpointShard(folder.Folder,0,1,cloudCheckpointTest.identity(),...
                Config=cloudCheckpointTest.config(),RunTrial=runTrial,RequestedWorkers=2,...
                AckPollSeconds=0.02,AckTimeoutSeconds=30);
            saved = load(fullfile(folder.Folder,'results','benchmark_results.mat'));

            testCase.verifyEqual(first,resumed);
            testCase.verifyTrue(all(saved.trialResults.completed));
            testCase.verifyEqual(cloudCheckpointTest.counts(folder.Folder),ones(5,1));
            testCase.verifyEqual(saved.trialResults.success,[true;false;false;false;true]);
        end
    end
    methods (Static)
        function result = invalidTrial(varargin)
            result = fpf.initializeRunResult(varargin{1:6},1);
            result.success = false;
            result.rawSincReference = [.4 .1];
            result.referenceResult = struct('metrics',struct('functionEvaluations',10));
            result.mziResult = struct('metrics',struct('functionEvaluations',10),...
                'realizedCoefficientMatrix',NaN(4,3));
            result.diagnosticPayload = 'full-scientific-result';
        end
        function result = trial(folder,verifyPublished,varargin)
            parser = inputParser;
            parser.KeepUnmatched = true;
            addParameter(parser,'TrialIndex',1);
            parse(parser,varargin{7:end});
            id = parser.Results.TrialIndex;
            file = fopen(fullfile(folder,sprintf('calls_%d.txt',id)),'a');
            assert(file>=0,'fixture:Write','Cannot record trial call.');
            fprintf(file,'%d\n',id);
            fclose(file);
            if verifyPublished && id>1
                saved = load(fullfile(folder,'results','benchmark_results.mat'));
                assert(saved.trialResults.completed(id-1),'fixture:PublishOrder','Previous trial MAT not published.');
                csv = readtable(fullfile(folder,'results','trial_results.csv'));
                assert(csv.completed(id-1),'fixture:PublishOrder','Previous trial CSV not published.');
            end
            if id==3, error('fixture:ScienceFailure','Simulated scientific exception.'); end
            pause(0.02);
            result = fpf.initializeRunResult(varargin{1:6},id);
            result.success = id==1 || id==5;
            result.completed = true;
            result.rawSincReference = [0.4 .1];
            result.referenceResult = struct('metrics',struct('functionEvaluations',10));
            result.mziResult = struct('metrics',struct('functionEvaluations',10),...
                'realizedCoefficientMatrix',zeros(4,3));
            result.diagnosticPayload = complex([id id+1],[id+2 id+3]);
            if id==4
                result.mziResult = [];
                result.failureIdentifier = "fixture:StageFailure";
                result.failureStage = "mzi";
                result.failureMessage = "Synthetic returned stage failure";
            end
        end
        function config = config()
            config = fpf.benchmarkConfig();
            config.firOrders = 4;
            config.passbandRatios = .2;
            config.randomSeeds = 0;
            config.referenceSolvers = 0;
            config.mziSolvers = 1;
            config.N_tr = 5;
            config.N_s = 21;
        end
        function value = identity()
            value = struct('run_id','synthetic-test','source_sha256',repmat('a',1,64),...
                'config_sha256',repmat('b',1,64));
        end
        function value = path(folder,id)
            value = fullfile(folder,'results','checkpoints',sprintf('trial_%012d.mat',id));
        end
        function value = counts(folder)
            value = zeros(5,1);
            for id=1:5
                path = fullfile(folder,sprintf('calls_%d.txt',id));
                if isfile(path), value(id)=numel(sscanf(fileread(path),'%d')); end
            end
        end
        function value = uploader(folder)
            value = timer('ExecutionMode','fixedSpacing','Period',.02,...
                'TimerFcn',@(~,~) cloudCheckpointTest.acknowledge(folder));
            start(value);
        end
        function acknowledge(folder)
            files = dir(fullfile(folder,'results','checkpoints','trial_*.json'));
            for index=1:numel(files)
                sidecar = jsondecode(fileread(fullfile(files(index).folder,files(index).name)));
                path = fullfile(folder,'results','acks',files(index).name);
                if isfile(path), continue; end
                ack = cloudCheckpointTest.identity();
                ack.trial_id = sidecar.trial_id;
                ack.sha256 = fpf.cloudFileSha256(cloudCheckpointTest.path(folder,sidecar.trial_id));
                fpf.writeCloudJson(path,ack);
            end
        end
        function closePool()
            pool = gcp('nocreate');
            if ~isempty(pool), delete(pool); end
        end
        function closeUploader(uploader)
            stop(uploader);
            delete(uploader);
        end
    end
end
