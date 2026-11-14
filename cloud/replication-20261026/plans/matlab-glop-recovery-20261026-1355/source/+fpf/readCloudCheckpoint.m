function [checkpoint,acknowledged,sha256] = readCloudCheckpoint(path,parameter,globalId,identity,ackDirectory)
%READCLOUDCHECKPOINT Validate identity/content and the durable-upload receipt.
    try
        saved = load(path,'checkpoint');
        checkpoint = saved.checkpoint;
        assert(checkpoint.schemaVersion==1 && checkpoint.globalId==globalId);
        assert(isequal(checkpoint.parameters,parameter));
        for field = ["run_id","source_sha256","config_sha256"]
            assert(strcmp(checkpoint.identity.(field),identity.(field)));
        end
        assert(islogical(checkpoint.success) && isscalar(checkpoint.success));
        assert(isstruct(checkpoint.result) && isscalar(checkpoint.result));
        assert(isequal(checkpoint.success,logical(checkpoint.result.success)));
        for field = ["error","evaluations","legacyError","legacyEvaluations","elapsedSeconds"]
            value = checkpoint.(field);
            assert(isnumeric(value) && isreal(value) && isscalar(value));
        end
        assert(isfinite(checkpoint.elapsedSeconds) && checkpoint.elapsedSeconds>=0);
        if checkpoint.success
            assert(isequaln(checkpoint.legacyError,checkpoint.error));
            assert(isequaln(checkpoint.legacyEvaluations,checkpoint.evaluations));
        else
            assert(checkpoint.legacyError==0 && checkpoint.legacyEvaluations==0);
        end
    catch exception
        error('fpf:CorruptCheckpoint','Invalid checkpoint %s: %s',path,exception.message);
    end
    sha256 = fpf.cloudFileSha256(path);
    ackPath = fullfile(ackDirectory,sprintf('trial_%012d.json',globalId));
    acknowledged = false;
    if ~isfile(ackPath), return; end
    try
        ack = jsondecode(fileread(ackPath));
        assert(ack.trial_id==globalId && strcmp(ack.sha256,sha256));
        for field = ["run_id","source_sha256","config_sha256"]
            assert(strcmp(ack.(field),identity.(field)));
        end
    catch exception
        error('fpf:InvalidCloudAcknowledgement','Invalid durable receipt %s: %s',ackPath,exception.message);
    end
    acknowledged = true;
end
