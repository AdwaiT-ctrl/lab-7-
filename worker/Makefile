VERSION=v1
REGISTRY=YOUR_DOCKER_USERNAME_HERE
IMAGE=$(REGISTRY)/demucs-worker

build:
	docker build -f Dockerfile -t $(IMAGE):$(VERSION) .
push:
	docker push $(IMAGE):$(VERSION)
