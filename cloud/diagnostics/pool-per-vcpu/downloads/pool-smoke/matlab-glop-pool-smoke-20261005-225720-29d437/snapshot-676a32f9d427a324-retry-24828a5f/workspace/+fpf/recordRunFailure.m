function result = recordRunFailure(result,stage,exception)
%RECORDRUNFAILURE Attach a failed stage and its exception to a trial result.

    result.failureStage = stage;
    result.failureIdentifier = string(exception.identifier);
    result.failureMessage = string(exception.message);
end
