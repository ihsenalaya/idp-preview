# idp-testing

Demo application used to validate the Cellenza preview environment flow.

## Preview flow

When a pull request is opened, updated, or reopened:

1. GitHub Actions runs on the local self-hosted runner labeled `kind`.
2. Kaniko builds the Flask application image inside the Kubernetes cluster.
3. The image is pushed to GHCR as `ghcr.io/ihsenalaya/idp-testing:<commit-sha>`.
4. The workflow creates a GitHub Deployment for `pr-<number>`.
5. The workflow creates a short-lived token Secret for the Cellenza controller.
6. The workflow applies a `Cellenza` resource with `spec.github.enabled=true`.
7. The Cellenza controller provisions the preview environment and updates GitHub when the observed state is ready.

Cleanup is handled when the pull request is closed:

1. The workflow refreshes the short-lived token Secret.
2. The `Cellenza` resource is deleted.
3. The controller marks the GitHub Deployment as inactive during finalizer cleanup.
4. The token Secret is removed.

## Required local cluster components

- A Kind cluster reachable from the self-hosted runner.
- `cellenza-operator` installed in `cellenza-operator-system`.
- A namespace named `github-runner`.
- The runner must have the labels `self-hosted` and `kind`.
- The runner service account must be allowed to create Jobs and Secrets in `github-runner`, create the GitHub token Secret in `cellenza-operator-system`, and apply/delete `Cellenza` resources.

For a local Kind cluster, expose ingress before opening the preview URL:

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80
```

Then `http://pr-<number>.preview.localtest.me:8080` routes to the preview app from the PC.

## Application

The app is intentionally small:

- `GET /` displays the branch and pull request number.
- `GET /healthz` returns `ok`.
- The container listens on port `80`.
