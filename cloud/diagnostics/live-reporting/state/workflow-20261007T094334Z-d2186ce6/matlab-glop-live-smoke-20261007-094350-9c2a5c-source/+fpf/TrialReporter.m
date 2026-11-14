classdef TrialReporter < handle
    % One independent trial's result and throttled worker activity records.
    properties (Access = private)
        Directory
        Clock
        LastWrite = 0
        State
    end
    methods
        function reporter = TrialReporter(directory,globalId,parameters)
            reporter.Directory = string(directory);
            reporter.Clock = tic;
            reporter.State = struct('schema_version',1,...
                'worker_pid',feature('getpid'),'global_trial_id',globalId,...
                'parameters',parameters,'started_at',fpf.TrialReporter.utcNow(),...
                'stage','starting','active',true,'objective_evaluations',0,...
                'stage_evaluations',0,'last_objective',NaN,'best_stage_objective',NaN);
            reporter.publish();
        end
        function stage(reporter,name)
            reporter.State.stage = char(name);
            reporter.State.stage_evaluations = 0;
            reporter.State.best_stage_objective = NaN;
            reporter.publish();
        end
        function evaluated(reporter,value)
            reporter.State.objective_evaluations = reporter.State.objective_evaluations+1;
            reporter.State.stage_evaluations = reporter.State.stage_evaluations+1;
            reporter.State.last_objective = value;
            if isscalar(value) && isfinite(value) && ...
                    (isnan(reporter.State.best_stage_objective) || value < reporter.State.best_stage_objective)
                reporter.State.best_stage_objective = value;
            end
            if toc(reporter.Clock)-reporter.LastWrite >= 5
                reporter.publish();
            end
        end
        function finish(reporter,result,endToEndError)
            status = 'nonconverged';
            if result.success
                status = 'succeeded';
            elseif (isfield(result,'failureIdentifier') && strlength(result.failureIdentifier) > 0) || ...
                    (isfield(result,'failureStage') && strlength(result.failureStage) > 0)
                status = 'failed';
            end
            record = struct('schema_version',1,...
                'global_trial_id',reporter.State.global_trial_id,...
                'parameters',reporter.State.parameters,...
                'started_at',reporter.State.started_at,...
                'completed_at',fpf.TrialReporter.utcNow(),...
                'elapsed_seconds',toc(reporter.Clock),'status',status,...
                'end_to_end_error',endToEndError,'result',result);
            path = fullfile(reporter.Directory,'trials',...
                sprintf('trial_%012d.json',reporter.State.global_trial_id));
            if isfile(path)
                error('fpf:DuplicateTelemetryTrial','Trial %d already has a live record.',...
                    reporter.State.global_trial_id);
            end
            fpf.writeLiveJson(path,record);
            reporter.State.stage = 'idle';
            reporter.State.active = false;
            reporter.publish();
        end
        function fail(reporter,exception)
            result = struct('success',false,'completed',false,...
                'failureStage',reporter.State.stage,...
                'failureIdentifier',exception.identifier,'failureMessage',exception.message);
            reporter.finish(result,NaN);
        end
    end
    methods (Access = private)
        function publish(reporter)
            reporter.State.updated_at = fpf.TrialReporter.utcNow();
            reporter.State.elapsed_seconds = toc(reporter.Clock);
            fpf.writeLiveJson(fullfile(reporter.Directory,'workers',...
                sprintf('worker_%d.json',reporter.State.worker_pid)),reporter.State);
            reporter.LastWrite = toc(reporter.Clock);
        end
    end
    methods (Static)
        function value = utcNow()
            value = char(datetime('now',TimeZone='UTC',...
                Format="yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"));
        end
    end
end
