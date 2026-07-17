# Cluster Build Helpers

These manifests are optional helpers for environments that intentionally build
images inside Kubernetes. The preferred release path is usually to build images
outside the cluster and push them to a private registry.

Example image targets:

- `ghcr.io/example/asgardian-backend:0.4.2-arm64`
- `ghcr.io/example/asgardian-web:0.4.2-arm64`

`registry-push-job.yaml` builds from a minimal source bundle and pushes directly
to a configured registry. The bundle must contain only the files required for a
clean build and must not contain secrets, local diagnostics, generated media, or
environment-specific artifacts.

The cluster should use a registry pull secret such as `asgardian-registry` with
type `kubernetes.io/dockerconfigjson`.

If builds are performed locally or in CI, these helpers are not required.

## Files

- `workspace.yaml`: optional persistent workspace used by the in-cluster build
  jobs.
- `buildkit-job.yaml`: builds backend and web images into local tar archives.
- `import-job.yaml`: imports locally built image tar archives into a
  containerd-based Kubernetes node.
- `registry-push-job.yaml`: builds backend and web images and pushes them to a
  configured registry.

These manifests are intentionally generic. Before use, review image names,
registry credentials, node selectors, storage class names, and resource limits
for your cluster.