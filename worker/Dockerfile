FROM xserrat/facebook-demucs:latest
WORKDIR /srv
COPY requirements.txt /tmp/worker-requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/worker-requirements.txt
COPY worker-server.py /srv/worker-server.py
CMD ["python3", "/srv/worker-server.py"]
