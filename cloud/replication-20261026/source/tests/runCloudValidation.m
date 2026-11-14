% Isolated validation: synthetic results, actual two-process scheduling.
source = fileparts(fileparts(mfilename('fullpath')));
cd(source);
addpath(source);
results = runtests(fullfile(source,'tests','cloudCheckpointTest.m'));
disp(table(results));
output = fullfile(source,'tests','output');
save(fullfile(output,'final-test-results.mat'),'results');
report = struct('name',{results.Name},'passed',num2cell([results.Passed]),...
    'failed',num2cell([results.Failed]),'duration',num2cell([results.Duration]));
file = fopen(fullfile(output,'final-test-results.json'),'w');
fprintf(file,'%s',jsonencode(report,PrettyPrint=true)); fclose(file);
names = ["runCloudCheckpointShard","runCloudCheckpointTrial","readCloudCheckpoint",...
    "cloudFileSha256","writeCloudJson","TrialReporter","runCloudCheckpointSmoke",...
    "runCloudRecoverySmoke","cloudCheckpointSmokeTrial"];
analysis = struct();
for name = names
    analysis.(name) = checkcode(fullfile(source,'+fpf',name+'.m'),'-id');
end
file = fopen(fullfile(output,'code-analyzer.json'),'w');
fprintf(file,'%s',jsonencode(analysis,PrettyPrint=true)); fclose(file);
assert(all([results.Passed]),'Cloud validation failed.');
