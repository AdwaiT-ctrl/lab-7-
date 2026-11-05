VERSION=v1
REGISTRY=YOUR_DOCKER_USERNAME_HERE
IMAGE=$(REGISTRY)/demucs-rest

build:
	docker build -f Dockerfile-rest -t $(IMAGE):$(VERSION) .

push:
	docker push $(IMAGE):$(VERSION)
