#!/usr/bin/env python3
"""REST API for queuing and retrieving Demucs separated tracks."""

import base64
import hashlib
import json
import os
import platform
import sys

import redis
from flask import Flask, jsonify, request, send_file
from minio import Minio
from minio.error import S3Error
from io import BytesIO


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "rootuser")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "rootpass123")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
QUEUE_BUCKET = os.getenv("QUEUE_BUCKET", "queue")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "output")
QUEUE_KEY = "toWorker"
LOG_KEY = "logging"


def clients():
    return (
        redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, socket_connect_timeout=5),
        Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY,
              secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE),
    )


def log(message):
    try:
        r, _ = clients()
        r.lpush(LOG_KEY, f"{platform.node()}.rest: {message}")
    except Exception as exc:
        print(f"log unavailable: {exc}", file=sys.stderr)


def ensure_bucket(client, name):
    if not client.bucket_exists(name):
        client.make_bucket(name)


@app.get("/")
def health():
    return "<h1>Music Separation Server</h1><p>Use a valid endpoint.</p>"


@app.post("/apiv1/separate")
def separate():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(reason="Expected a JSON object"), 400
    encoded = data.get("mp3")
    if not isinstance(encoded, str):
        return jsonify(reason="mp3 must be a base64 encoded string"), 400
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        return jsonify(reason="mp3 is not valid base64"), 400
    if not audio:
        return jsonify(reason="mp3 may not be empty"), 400

    model = data.get("model", os.getenv("DEMUCS_MODEL", "mdx_extra_q"))
    if not isinstance(model, str) or not model or len(model) > 100:
        return jsonify(reason="model must be a non-empty string"), 400
    songhash = hashlib.sha256(audio).hexdigest()[:40]
    job = {"songhash": songhash, "model": model,
           "object": f"{songhash}.mp3", "callback": data.get("callback")}
    try:
        r, storage = clients()
        ensure_bucket(storage, QUEUE_BUCKET)
        storage.put_object(QUEUE_BUCKET, job["object"], BytesIO(audio), len(audio),
                           content_type="audio/mpeg")
        r.lpush(QUEUE_KEY, json.dumps(job))
    except Exception as exc:
        log(f"enqueue failed for {songhash}: {exc}")
        return jsonify(reason="Unable to queue song"), 503
    log(f"queued song {songhash}")
    return jsonify(hash=songhash, reason="Song enqueued for separation")


@app.get("/apiv1/queue/")
@app.get("/apiv1/queue")
def queue():
    try:
        r, _ = clients()
        entries = r.lrange(QUEUE_KEY, 0, -1)
        parsed = []
        for entry in entries:
            raw = entry.decode("utf-8")
            try:
                job = json.loads(raw)
                parsed.append(job.get("songhash", raw))
            except (ValueError, AttributeError):
                parsed.append(raw)
        return jsonify(queue=parsed)
    except Exception as exc:
        return jsonify(reason=f"Queue unavailable: {exc}"), 503


@app.get("/apiv1/track/<songhash>/<track>")
def get_track(songhash, track):
    if not songhash.isalnum() or track not in {"base.mp3", "bass.mp3", "vocals.mp3", "drums.mp3", "other.mp3"}:
        return jsonify(reason="Invalid song hash or track"), 400
    stem = "other" if track == "base.mp3" else track[:-4]
    try:
        _, storage = clients()
        obj = storage.get_object(OUTPUT_BUCKET, f"{songhash}-{stem}.mp3")
        body = obj.read()
        obj.close()
        obj.release_conn()
        return send_file(BytesIO(body), mimetype="audio/mpeg",
                         as_attachment=True, download_name=track)
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            return jsonify(reason="Track is not available"), 404
        return jsonify(reason="Unable to retrieve track"), 503
    except Exception as exc:
        return jsonify(reason=f"Unable to retrieve track: {exc}"), 503


@app.route("/apiv1/remove/<songhash>/<track>", methods=["GET", "DELETE"])
def remove_track(songhash, track):
    if not songhash.isalnum() or track not in {"base.mp3", "bass.mp3", "vocals.mp3", "drums.mp3", "other.mp3"}:
        return jsonify(reason="Invalid song hash or track"), 400
    stem = "other" if track == "base.mp3" else track[:-4]
    try:
        _, storage = clients()
        storage.remove_object(OUTPUT_BUCKET, f"{songhash}-{stem}.mp3")
        return jsonify(reason="Track removed", hash=songhash, track=track)
    except Exception as exc:
        return jsonify(reason=f"Unable to remove track: {exc}"), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
