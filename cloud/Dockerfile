ARG MATLAB_IMAGE
FROM ${MATLAB_IMAGE}

# Use a prepared MATLAB image with the required toolboxes and licensing.
# Copy only executable project sources; retain the base image's user.
COPY main.m /opt/glop-cmp/main.m
COPY +fpf/ /opt/glop-cmp/+fpf/
WORKDIR /opt/glop-cmp
