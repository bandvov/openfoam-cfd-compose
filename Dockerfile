# Tags published on Docker Hub for openeuler/openfoam include 2506-oe2403sp2,
# 2506-oe2403sp1 and 2412-oe2403sp1. Override with:
#   docker compose build --build-arg OPENFOAM_IMAGE_TAG=<tag>
ARG OPENFOAM_IMAGE_TAG=2506-oe2403sp2
FROM openeuler/openfoam:${OPENFOAM_IMAGE_TAG}

USER root
RUN dnf install -y bash python3 python3-pip && dnf clean all

ENV PYTHONUNBUFFERED=1

WORKDIR /workspace
COPY requirements.txt /workspace/requirements.txt

# --break-system-packages only exists in pip >= 23.0.1; fall back without it.
RUN python3 -m pip install --no-cache-dir --break-system-packages -r /workspace/requirements.txt \
    || python3 -m pip install --no-cache-dir -r /workspace/requirements.txt

# Override the broken relative entrypoint
ENTRYPOINT []
CMD ["python3", "/workspace/run.py"]
