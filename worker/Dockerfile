FROM xserrat/facebook-demucs:latest
WORKDIR /srv
COPY requirements.txt /tmp/worker-requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/worker-requirements.txt
COPY worker-server.py /srv/worker-server.py
# The upstream image has ENTRYPOINT ["/bin/bash", "--login", "-c"].
# Replace it so the consumer process runs directly and remains alive on BLPOP.
ENTRYPOINT ["python3", "/srv/worker-server.py"]
