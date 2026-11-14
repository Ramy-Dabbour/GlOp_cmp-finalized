function writeLiveJson(path,value)
%WRITELIVEJSON Publish a complete UTF-8 record by atomic file replacement.
    temporary = string(path) + ".tmp-" + string(feature('getpid'));
    [file,message] = fopen(temporary,'w','n','UTF-8');
    if file < 0
        error('fpf:TelemetryWrite','Cannot open live record: %s',message);
    end
    cleanup = onCleanup(@() fclose(file));
    fprintf(file,'%s',jsonencode(fpf.jsonSafe(value)));
    clear cleanup
    [ok,message] = movefile(temporary,path,'f');
    if ~ok
        error('fpf:TelemetryWrite','Cannot publish live record: %s',message);
    end
end
