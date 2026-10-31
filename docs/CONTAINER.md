# Throw zero in a container (repository isolation)

**State: Written and verified only with fake `docker`** (built command is tested, `sh -n` OK). The image was **never
built** and no container has been launched: no Docker or podman where this work was done. To be validated at home (§ Validation).

## Why not a “container backend” in `--sandbox`

`--sandbox` wraps each command (installation, launch) to execute it on the host with reduced rights. Or zero downloads
for **the host platform** the runtimes (Node, uv, Go…) in `~/.zero` and write their paths in the commands. Under macOS these
binaries do not run in a Linux container; under Linux, this would only work with a compatible glibc image. Make believe that
this works would have required rewriting the runtime resolution without being able to test it. Instead: **zero rotates itself in the
container** — he installs his Linux runtimes there and launches the repository, without knowing anything about the border.

## Usage

    docker build -f contrib/Dockerfile -t zerodev:latest .          # once (podman: same command)
    contrib/zero-container.sh ~/code/projet-douteux # = zero ~/code/projet-douteux, but in a container
    ZERO_PORTS="3000 8000" contrib/zero-container.sh ~/code/project --services local

The script passes to the container: `--cap-drop ALL`, `no-new-privileges`, process limit (`ZERO_PIDS`, 1024) and memory limit (`ZERO_MEMORY`, 4g),
the repository mounted in `/work` (**read/write**: `node_modules` and generated files land there), a volume `zerodev-home` for `~/.zero`
(runtimes and caches reused from one launch to another). The rest of your machine — `~`, SSH keys, other repositories — is not visible.

## Limits (to know)

- **Network not cut**: the installation requires the network; the project can therefore issue outgoing connections.
- **Ports**: Publish them with `ZERO_PORTS`, and the application should listen on `0.0.0.0`, not `127.0.0.1` (otherwise it is unreachable from the host).
- **Services** (Postgres, Redis, etc.): no Docker in the container, so `--services local` mandatory and the corresponding binaries must be
  present in the image (they are not: add them to `contrib/Dockerfile` if necessary, or start the services on the host).
- **GPU**: not transmitted. **SELinux** (Fedora, podman): `ZERO_VOLUME_OPTS=":Z"`.
- The repository mounted for writing remains modifiable by the project: this is the only place where it can write permanently.
- A container is not an absolute guarantee (shared core); in addition to `--cap-drop ALL`, prefer podman without rights (rootless).

## Validation (to be done, with a trust deposit first)

1. `docker build -f contrib/Dockerfile -t zerodev:latest .` succeeds; `docker run --rm zerodev:latest --version` displays the version.
2. `contrib/zero-container.sh examples/node-app`: The example installs and responds (with `ZERO_PORTS=<port>`).
3. Isolation: `contrib/zero-container.sh <dépôt> --cmd "ls ~/.ssh"` should not show anything from your personal file.
4. Paste the first error encountered here: the most likely is a missing system package in the image.
