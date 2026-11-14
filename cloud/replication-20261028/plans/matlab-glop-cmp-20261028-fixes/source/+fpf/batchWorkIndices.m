function workIndices = batchWorkIndices(totalTests,taskIndex,taskCount)
%BATCHWORKINDICES Map a zero-based Batch task to disjoint global trial IDs.
    validateattributes(totalTests,"double",...
        {"scalar","real","finite","integer",">=",1,"<=",flintmax});
    validateattributes(taskCount,"double",...
        {"scalar","real","finite","integer",">=",1,"<=",100000});
    validateattributes(taskIndex,"double",...
        {"scalar","real","finite","integer",">=",0,"<",taskCount});
    workIndices = (taskIndex + 1:taskCount:totalTests).';
end
