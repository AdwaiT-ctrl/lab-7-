# MinIO deployment

The active MinIO deployment is defined by `minio-deployment.yaml` and
`minio-external-service.yaml`. Despite the service filename, the service is a
normal in-cluster `ClusterIP` service named `minio`; REST and worker pods reach
the S3 API at `minio:9000`.

The deployment uses a 20 GiB persistent volume claim and the public
`cgr.dev/chainguard/minio:latest` image. Its non-root container writes to the
volume using the pod's `fsGroup: 65532` setting. Create the credentials before
applying the deployment:

```sh
kubectl create secret generic minio-credentials \
  --from-literal=username='YOUR_MINIO_USERNAME' \
  --from-literal=password='YOUR_LONG_MINIO_PASSWORD'
```

The REST API creates the `queue` and `output` buckets on first use. The
`minio-config.yaml` file is retained from the original Helm tutorial scaffold;
the current deployment does not consume it. Credentials for the active
deployment come only from the `minio-credentials` Kubernetes Secret.
