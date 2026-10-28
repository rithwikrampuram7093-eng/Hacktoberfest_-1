FROM python:3.12-slim

# Dependencies are installed while building this trusted image, never at test time.
RUN pip install --no-cache-dir --upgrade pip==26.2.2 pytest==9.0.3 pytest-asyncio==1.4.1
RUN mkdir -p /opt/rootcause /work && chown 10001:10001 /work
COPY runner.py /opt/rootcause/runner.py
RUN chmod 0555 /opt/rootcause/runner.py
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["python", "-I", "/opt/rootcause/runner.py"]
