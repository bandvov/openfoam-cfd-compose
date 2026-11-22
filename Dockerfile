FROM openeuler/openfoam:2506-oe2403sp4

USER root
RUN dnf install -y bash python3 python3-pip && dnf clean all

WORKDIR /workspace
COPY requirements.txt /workspace/requirements.txt

RUN python3 -m pip install --break-system-packages --no-cache-dir -r /workspace/requirements.txt

# Override the broken relative entrypoint
ENTRYPOINT []
CMD ["python3", "/workspace/run.py"]