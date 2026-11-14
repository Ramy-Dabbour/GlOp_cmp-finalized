function result = liveSmokeTrial(varargin)
    parser = inputParser;
    parser.KeepUnmatched = true;
    addParameter(parser,'TrialIndex',1);
    parse(parser,varargin{7:end});
    reporter = fpf.currentReporter();
    reporter.stage("fixture");
    seconds = 2;
    if parser.Results.TrialIndex == 16
        seconds = 60;
    end
    for index = 1:seconds
        pause(1);
        reporter.evaluated(1/index);
    end
    result = parallelSweepTest.seededTrial(varargin{:});
end
