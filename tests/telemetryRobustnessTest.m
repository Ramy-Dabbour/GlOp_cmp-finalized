classdef telemetryRobustnessTest < matlab.unittest.TestCase
    % Covers: best-effort worker telemetry, retrying live-record publication, and
    % treating an eig failure inside the admissibility test as a penalized candidate.
    methods (TestClassSetup)
        function paths(testCase)
            folder = fileparts(mfilename('fullpath'));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fileparts(folder)));
        end
    end
    methods (Test)
        function lockedWorkerFileDoesNotAbortTheSolver(testCase)
            testCase.assumeTrue(ispc,'File-lock behavior is Windows-specific.');
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            mkdir(fullfile(folder.Folder,'trials'));
            mkdir(fullfile(folder.Folder,'workers'));
            reporter = fpf.TrialReporter(folder.Folder,1,[4 .2 0 1 1 1]);
            workerFile = fullfile(folder.Folder,'workers', ...
                sprintf('worker_%d.json',feature('getpid')));
            holder = fopen(workerFile,'r');
            testCase.assertGreaterThan(holder,0);
            testCase.addTeardown(@() telemetryRobustnessTest.closeIfOpen(holder));
            reporter.stage("mzi");          % must not throw while the file is held
            telemetryRobustnessTest.closeIfOpen(holder);
            reporter.stage("reference");    % and must publish normally afterwards
        end

        function publishRetriesWhenTheDestinationIsBrieflyLocked(testCase)
            testCase.assumeTrue(ispc,'File-lock behavior is Windows-specific.');
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            target = fullfile(folder.Folder,'record.json');
            fpf.writeLiveJson(target,struct('a',1));
            holder = fopen(target,'r');
            testCase.addTeardown(@() telemetryRobustnessTest.closeIfOpen(holder));
            release = timer('StartDelay',0.12, ...
                'TimerFcn',@(~,~) telemetryRobustnessTest.closeIfOpen(holder));
            testCase.addTeardown(@() delete(release));
            start(release);
            fpf.writeLiveJson(target,struct('a',2));
            testCase.verifyEqual(jsondecode(fileread(target)).a,2);
        end

        function eigNonConvergenceBecomesAPenalizedStage2Candidate(testCase)
            stageCount = 5;
            referenceVector = [0.5 0 0 0 0];
            reference = fpf.referenceSMatrixCoefficients(referenceVector,stageCount,2.*stageCount);
            originalRandomState = rng;
            testCase.addTeardown(@() rng(originalRandomState));
            rng(1);
            design = rand(1,stageCount + 1);
            control = fpf.evaluateMziSolution(design,stageCount,reference,CollectDiagnostics=false);
            testCase.assumeTrue(control.isResponseNormalized);
            testCase.assumeLessThan(control.normalizedFrobeniusError,realmax);

            telemetryRobustnessTest.shadowRootsWithEigFailure(testCase);
            result = fpf.evaluateMziSolution(design,stageCount,reference,CollectDiagnostics=false);
            testCase.verifyFalse(result.isResponseNormalized);
            testCase.verifyEqual(result.normalizedFrobeniusError,realmax);
        end
    end
    methods (Static)
        function closeIfOpen(fid)
            if any(openedFiles == fid)
                fclose(fid);
            end
        end
        function shadowRootsWithEigFailure(testCase)
            testCase.applyFixture(matlab.unittest.fixtures.SuppressedWarningsFixture( ...
                'MATLAB:dispatcher:nameConflict'));
            shadow = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            fid = fopen(fullfile(shadow.Folder,'roots.m'),'w');
            fprintf(fid,"function r = roots(~)\n");
            fprintf(fid,"error('MATLAB:eig:NoConvergence','Algorithm did not succeed.');\n");
            fprintf(fid,"end\n");
            fclose(fid);
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(shadow.Folder));
        end
    end
end
