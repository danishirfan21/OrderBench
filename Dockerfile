# Reference evaluation image. The base is pinned by digest (python:3.12.8-slim-bookworm).
FROM python@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --no-deps -r /tmp/requirements.lock && rm /tmp/requirements.lock

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin runner
USER 10001
WORKDIR /workspace
