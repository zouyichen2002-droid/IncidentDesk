FROM python:3.12.13-slim-bookworm
COPY analyze.py /opt/analyze.py
USER 65532:65532
ENTRYPOINT ["python","-I","/opt/analyze.py"]
