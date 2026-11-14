function writeCloudJson(path,value)
%WRITECLOUDJSON Durably publish complete checkpoint/control JSON.
% Unlike advisory telemetry, every I/O failure must propagate to the caller.
    directory = fileparts(path);
    temporary = string(tempname(directory))+'.json';
    [file,message] = fopen(temporary,'wb');
    if file < 0, error('fpf:CheckpointWrite','Cannot open %s: %s',temporary,message); end
    cleanup = onCleanup(@() fclose(file));
    bytes = unicode2native(jsonencode(value),'UTF-8');
    count = fwrite(file,bytes,'uint8');
    if count ~= numel(bytes), error('fpf:CheckpointWrite','Short write to %s.',temporary); end
    clear cleanup
    fpf.atomicReplace(temporary,path);
end
