FROM python:3.12-slim

RUN set -eux; \
    apt-get update; \
    (apt-get install -y --no-install-recommends libglib2.0-0t64 || \
     apt-get install -y --no-install-recommends libglib2.0-0); \
    apt-get install -y --no-install-recommends \
        build-essential g++ \
        libsm6 libxext6 libxrender1 \
        v4l-utils \
    ; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN g++ converter.cpp -o stereo -O3 -march=native -ffast-math -pthread

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1
