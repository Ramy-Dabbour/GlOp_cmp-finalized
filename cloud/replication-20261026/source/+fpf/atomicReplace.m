function atomicReplace(temporary,destination)
%ATOMICREPLACE Commit a closed file with a same-filesystem atomic rename.
%   Never fall back to copy/delete: a failed commit must remain detectable.
    file = java.io.RandomAccessFile(char(temporary),'rw');
    cleanup = onCleanup(@() file.close());
    file.getChannel().force(true);
    clear cleanup
    source = java.io.File(char(temporary)).toPath();
    target = java.io.File(char(destination)).toPath();
    options = javaArray('java.nio.file.CopyOption',2);
    options(1) = java.nio.file.StandardCopyOption.ATOMIC_MOVE;
    options(2) = java.nio.file.StandardCopyOption.REPLACE_EXISTING;
    java.nio.file.Files.move(source,target,options);
end
