function benchmarkResults = runCloudRecoverySmoke(taskRoot,taskIndex,taskCount,identity)
%RUNCLOUDRECOVERYSMOKE Intentionally hard-crash attempt zero; resume on retry.
% Launch only under the separate smoke manifest/run URI. Batch supplies the
% retry counter. Every trial is synthetic; no optimizer is invoked.
    attemptText = getenv('BATCH_TASK_RETRY_ATTEMPT');
    if isempty(attemptText), attemptText = '0'; end
    attempt = str2double(attemptText);
    if ~isscalar(attempt) || ~isfinite(attempt) || attempt<0 || attempt~=fix(attempt)
        error('fpf:InvalidRetryAttempt','BATCH_TASK_RETRY_ATTEMPT must be a nonnegative integer.');
    end
    threshold = Inf;
    if attempt==0, threshold = 3; end
    fprintf('Synthetic recovery smoke: retry attempt %d, hard-crash threshold %g.\n',attempt,threshold);
    benchmarkResults = fpf.runCloudCheckpointSmoke(taskRoot,taskIndex,taskCount,identity,...
        HardCrashAfterCommits=threshold);
end
