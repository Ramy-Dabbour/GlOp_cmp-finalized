function value = cloudFileSha256(path)
%CLOUDFILESHA256 Hash exact file bytes, including binary MAT contents.
    [file,message] = fopen(path,'rb');
    if file < 0, error('fpf:CheckpointRead','Cannot read %s: %s',path,message); end
    cleanup = onCleanup(@() fclose(file));
    digest = java.security.MessageDigest.getInstance('SHA-256');
    while ~feof(file)
        bytes = fread(file,1048576,'*uint8');
        digest.update(bytes);
    end
    [message,number] = ferror(file);
    if number ~= 0, error('fpf:CheckpointRead','Cannot hash %s: %s',path,message); end
    value = lower(reshape(dec2hex(typecast(digest.digest(),'uint8'),2).',1,[]));
end
