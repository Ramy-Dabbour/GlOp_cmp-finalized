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
    % Windows can hold a destination briefly (scanner, viewer, sync client).
    for attempt = 1:5
        [ok,message] = movefile(temporary,path,'f');
        if ok
            break
        end
        pause(0.05*attempt);
    end
    if ~ok
        error('fpf:TelemetryWrite','Cannot publish live record: %s',message);
    end
end
