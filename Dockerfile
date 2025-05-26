FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y build-essential g++ && \
    apt-get clean

WORKDIR /app
COPY . /app

RUN g++ converter.cpp -o stereo -O3 -march=native -ffast-math -pthread

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1
