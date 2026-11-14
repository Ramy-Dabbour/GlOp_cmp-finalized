function handleRunFailure(result,exception,options)
%HANDLERUNFAILURE Report or rethrow a failure using the run options.

    if options.Verbose
        fprintf("\n%s stage failed: %s\n",result.failureStage,...
            result.failureMessage);
    end
    if options.ThrowOnFailure
        rethrow(exception);
    end
end
