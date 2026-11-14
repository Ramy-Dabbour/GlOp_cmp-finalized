function csvPath = defaultCsvPath(matFilePath)
%DEFAULTCSVPATH Use the MAT file directory and basename for CSV output.

    [folder,basename] = fileparts(matFilePath);
    csvPath = fullfile(folder,string(basename) + ".csv");
end
