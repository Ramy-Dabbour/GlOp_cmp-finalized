function [figureHandle,plotData] = plotResponses(result,numberOfPoints)
%PLOTRESPONSES Plot target and realized squared MZI responses.

    arguments
        result (1,1) struct
        numberOfPoints (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(numberOfPoints,2)}
    end

    frequencies = linspace(-0.5,0.5,numberOfPoints);
    referenceResponse = fpf.evaluateCosineLagResponse(...
        result.referenceCoefficientMatrix,frequencies);
    realizedResponse = real(fpf.evaluateLagResponse(...
        result.realizedCoefficientMatrix,frequencies));
    labels = ["|S11|^2","|S12|^2","|S21|^2","|S22|^2"];

    figureHandle = figure("Name","Squared transmission response comparison",...
        "NumberTitle","off");
    tiledlayout(2,2,"TileSpacing","compact");
    for row = 1:4
        nexttile;
        plot(frequencies,referenceResponse(row,:),"LineWidth",1.5);
        hold on;
        plot(frequencies,realizedResponse(row,:),"LineWidth",1.5);
        grid on;
        xlabel("Normalized frequency f");
        ylabel(labels(row));
        legend("Reference","Realized","Location","best");
        title(labels(row));
    end

    plotData = struct(...
        "frequencies",frequencies,...
        "referenceResponse",referenceResponse,...
        "realizedResponse",realizedResponse);
end
