FROM python:3.12-slim
WORKDIR /app
COPY localflow.tar.xz.b64 /tmp/localflow.tar.xz.b64
RUN base64 -d /tmp/localflow.tar.xz.b64 > /tmp/localflow.tar.xz \
 && tar -xJf /tmp/localflow.tar.xz -C /tmp \
 && cp -a /tmp/localflow-core/. /app/ \
 && rm -f /tmp/localflow.tar.xz.b64 /tmp/localflow.tar.xz \
 && pip install --no-cache-dir -e .
CMD ["./bin/start-api"]
