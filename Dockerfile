FROM python:3.12-slim

WORKDIR /app

COPY . /app/
RUN pip install --no-cache-dir .

RUN chmod +x /app/bin/start-api /app/bin/start-outbox /app/bin/start-calendar

CMD ["/app/bin/start-api"]
