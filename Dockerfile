FROM python:3.10.11-alpine AS builder

ENV PYTHONUNBUFFERED=1

# for psutil
RUN apk add --update --no-cache --virtual .tmp-build-deps \
        build-base \
        linux-headers \
    && mkdir -p /temp_requirements

COPY pyproject.toml /temp_requirements/

# README.md is required by the pyproject.toml
RUN echo "foo" > /temp_requirements/README.md && \
    PYTHONDONTWRITEBYTECODE=1 \
    pip install --no-cache-dir /temp_requirements \
    && rm -rf /temp_requirements \
    && apk del .tmp-build-deps \
    && rm -rf /var/cache/apk/*

FROM python:3.10.11-alpine
ENV PYTHONUNBUFFERED=1

# read below about why we run as root in deployment
# RUN addgroup -S appuser && adduser -S appuser -G appuser

COPY --from=builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/
COPY --from=builder /usr/local/bin/gunicorn /usr/local/bin/gunicorn

WORKDIR /app
COPY src gunicorn.config.py ./

# run as root in deployment; Cloud Run (and local mounts) may create
# env/secret files that are root-owned and unreadable by a non-root
# user.  If we ever drop privileges later it must happen after those
# files are read.
#USER appuser
CMD exec gunicorn -c gunicorn.config.py --bind 0.0.0.0:$PORT
