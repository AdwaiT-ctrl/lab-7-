#!/usr/bin/env python3
"""Blocking Redis consumer that runs Demucs and stores separated tracks."""

import json
import os
import platform
import shutil
import subprocess
import tempfile
import time

import redis
import requests
from minio import Minio
from minio.error import S3Error


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "rootuser")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "rootpass123")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
QUEUE_BUCKET = os.getenv("QUEUE_BUCKET", "queue")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "output")
QUEUE_KEY = "toWorker"


def log(redis_client, level, message):
    text = f"{platform.node()}.worker.{level}: {message}"
    print(text, flush=True)
    try:
        redis_client.lpush("logging", text)
    except redis.RedisError as exc:
        print(f"log unavailable: {exc}", flush=True)


def ensure_bucket(storage, name):
    if not storage.bucket_exists(name):
        storage.make_bucket(name)


def process(job, storage, redis_client):
    songhash = job["songhash"]
    model = job.get("model") or os.getenv("DEMUCS_MODEL", "mdx_extra_q")
    object_name = job.get("object", f"{songhash}.mp3")
    workdir = tempfile.mkdtemp(prefix="demucs-")
    try:
        source = os.path.join(workdir, "input.mp3")
        response = storage.get_object(QUEUE_BUCKET, object_name)
        try:
            with open(source, "wb") as audio:
                for block in response.stream(1024 * 1024):
                    audio.write(block)
        finally:
            response.close()
            response.release_conn()

        output = os.path.join(workdir, "output")
        command = ["python3", "-m", "demucs.separate", "--mp3", "--out", output,
                   "--name", model, source]
        log(redis_client, "info", f"starting separation for {songhash} with {model}")
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=int(os.getenv("DEMUCS_TIMEOUT", "7200")))
        if result.returncode:
            raise RuntimeError(f"Demucs exited {result.returncode}: {result.stdout[-4000:]}")

        candidates = os.path.join(output, model, "input")
        if not os.path.isdir(candidates):
            matches = [os.path.join(root, name)
                       for root, _, files in os.walk(output)
                       for name in files if name.endswith(".mp3")]
            tracks = {os.path.splitext(os.path.basename(path))[0]: path for path in matches}
        else:
            tracks = {os.path.splitext(name)[0]: os.path.join(candidates, name)
                      for name in os.listdir(candidates) if name.endswith(".mp3")}
        ensure_bucket(storage, OUTPUT_BUCKET)
        for stem in ("bass", "drums", "vocals", "other"):
            path = tracks.get(stem)
            if not path or not os.path.isfile(path):
                raise RuntimeError(f"Demucs output is missing {stem}.mp3")
            storage.fput_object(OUTPUT_BUCKET, f"{songhash}-{stem}.mp3", path,
                                content_type="audio/mpeg")

        callback = job.get("callback")
        if isinstance(callback, dict) and callback.get("url"):
            try:
                requests.post(callback["url"], json=callback.get("data", {}), timeout=10)
            except requests.RequestException as exc:
                log(redis_client, "debug", f"callback failed for {songhash}: {exc}")
        try:
            storage.remove_object(QUEUE_BUCKET, object_name)
        except S3Error:
            pass
        log(redis_client, "info", f"completed separation for {songhash}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0,
                               socket_connect_timeout=5, socket_keepalive=True)
    storage = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY,
                    secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)
    while True:
        try:
            item = redis_client.blpop(QUEUE_KEY, timeout=0)
            job = json.loads(item[1].decode("utf-8"))
            process(job, storage, redis_client)
        except Exception as exc:
            log(redis_client, "error", f"job failed: {exc}")
            time.sleep(2)


if __name__ == "__main__":
    main()
