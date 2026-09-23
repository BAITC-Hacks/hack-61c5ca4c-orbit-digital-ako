# Docker operations

[Русский](../../README.md) · [English](../../README.en.md) · [Қазақша](../../README.kk.md)

All commands start in the repository root. Docker Compose 2.24.0+ is required. The application service is `app`, its container port is 8000, and the default host binding is `127.0.0.1:8000`.

## Start and inspect

```sh
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 app
```

`/api/health` supplies the Docker health check. It checks the application response, not provider access or analysis quality. The image runs as UID/GID `10001:10001`, drops Linux capabilities in Compose and starts one Uvicorn worker. Node.js is used only in the build stage.

The image includes demonstration input and freshly built frontend assets. Source edits require a rebuild; the runtime does not mount your checkout. The default deployment is local and unauthenticated, not a shared public service.

## Storage and updates

The baseline CLI can also run without host Python. Store its reproducible outputs in the writable data volume:

```sh
docker compose exec -T app python run.py --out /data/baseline
docker compose exec -T app python check.py --out /data/baseline
```

`/data/baseline` is separate from uploaded projects and can be regenerated from the bundled input. The project backup procedure below copies `/data/projects` only.

Compose mounts the named volume `moneygraph_data` at `/data`. Uploaded sources, normalized tables, result versions, analyst cases and feedback are under `/data/projects`. Native `money_graph/projects/` is a different location.

```sh
git pull --ff-only
docker compose up --build -d
```

Wait for running analyses to finish before updating. Completed results survive recreation. The job registry is in memory; jobs and queue progress are not restored after a restart. Start interrupted analysis again from its project.

Use the same checkout/Compose project name to keep using the same volume. Changing the Compose project name creates a different volume unless explicitly configured otherwise. Git clones do not move volumes or private settings between computers.

`docker compose stop` pauses service use, `docker compose start` restarts it, and `docker compose down` removes containers/network but keeps the data volume. **`docker compose down -v` permanently deletes the volume; do not use it to update the application.**

## Consistent backup

Finish active analyses and use a new backup folder for each snapshot. PowerShell:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
docker compose stop app
docker compose cp app:/data/projects ./backups/projects
docker compose start app
```

For macOS/Linux, replace the first line with `mkdir -p backups`. Inspect that the backup contains project UUID directories with `project.json`, source files and completed result folders. Backups contain the uploaded data, so keep them private and separate from the API key. Root `backups/` is excluded from Git and the image build.

## Restore to a separate volume

These commands target a **new Compose project** called `moneygraph-restore`. They do not erase the existing volume. Stop the original service first because both deployments use the same host port. Choose another project name if you already used this one.

```sh
docker compose stop app
docker compose -p moneygraph-restore create --build app
docker compose -p moneygraph-restore cp ./backups/projects/. app:/data/projects
docker compose -p moneygraph-restore run --rm --no-deps --user 0:0 --cap-add CHOWN app chown -R 10001:10001 /data/projects
docker compose -p moneygraph-restore up -d
```

The one-off ownership adjustment is needed because copying from a host can create files owned by root. It grants only the temporary restore process the capability to change ownership; the normal service still runs without capabilities as UID 10001. The fixed target is the project's data directory.

Open the UI and verify the project list, a completed result and an exported dossier before treating the restore as successful. Keep using `docker compose -p moneygraph-restore ...` for this restored deployment. To switch back, stop that deployment and start the original with `docker compose start app`.

To migrate a **native** project store, use the same restore sequence with `./money_graph/projects/.` instead of `./backups/projects/.`. Stop the native server before copying. Do not copy the old `.local/auth.sqlite3` or account files: the current universal MVP does not use the previous account-based architecture.

## API settings and secrets

Copy `money_graph/.env.example` to `money_graph/.env` only when a file does not already exist, then set the key locally. An absent file is allowed. The image contains the SDK, so enabling questions needs runtime configuration, not a new build.

After changing the environment, recreate the service with `docker compose up -d --force-recreate app`. Do not share output from an expanded `docker compose config`, full `docker inspect`, `env` or similar commands: runtime credentials can appear there.

Deployment platforms may inject `OPENAI_API_KEY`/`OPENAI_MODEL` directly into the container's environment. The image also sets `MONEY_GRAPH_PROJECTS=/data/projects`, which must point to writable persistent storage. [Full external service contract](INTEGRATIONS.md).

## Build and portability boundaries

The Dockerfile uses Node 22 and Python 3.12 Linux images. npm installs from `package-lock.json`; Python requirements currently specify compatible version ranges, not a fully pinned transitive lock. Rebuilding on a later date can resolve newer Python dependencies or base-image revisions. Record the resulting image ID/digest when distributing a tested release.

Do not increase the number of workers or replicas: the current queue, locks and job registry are process-local. Containerization does not implement resource quotas per project, durable scheduling, user authentication, encryption or cross-user isolation.

See the Docker documentation for [optional environment files](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/), [persistent volumes](https://docs.docker.com/engine/storage/volumes/) and [copying files with Compose](https://docs.docker.com/reference/cli/docker/compose/cp/).
