# OpenSpeak in a container. Build:  docker build -t openspeak .
# Run:  docker run --rm -p 127.0.0.1:8765:8765 -v openspeak-data:/data openspeak
FROM python:3.12-slim

# Not root; the app keeps settings and sessions in /data, models in /data/cache.
RUN useradd --create-home --uid 1000 app && mkdir /data && chown app /data
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[local]"

USER app
ENV OPENSPEAK_HOME=/data \
    HF_HOME=/data/cache \
    OPENSPEAK_LOCAL_HOST=host.docker.internal \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8765/', timeout=3)"
# Inside a container "all interfaces" is the container's own; the port is only
# reachable from outside if you publish it (see the run command above).
CMD ["openspeak", "--host", "0.0.0.0", "--no-browser"]
