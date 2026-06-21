# YAW anchor — deployment (<anchor-host>)

The rendezvous anchor runs on **<server-host>** (host `survey.<server-host>`, Ubuntu, Python
3.8) as the `fnlr` user, behind nginx with the existing Let's Encrypt cert that
already covers `<anchor-host>`. The public site shows only an innocuous cover page; the
directory API and the client download live under unguessable paths.

## Live URLs

| What | URL |
|------|-----|
| Public cover page | `https://<anchor-host>/` |
| **Client anchor URL** (baked into the client) | `https://<anchor-host>/<anchor-path>` |
| Operator status page | `https://<anchor-host>/<anchor-path>/status` |
| **Secret download link** | `https://<anchor-host>/<download-path>/` |

The secret path segments live in [`anchor.env`](anchor.env) (`ANCHOR_API_PREFIX`,
`DOWNLOAD_TOKEN`). **Keep `deploy/` private** — it holds those secrets.

## Server layout

```
/home/fnlr/yaw-anchor/
  anchor/  wasteproto/        # app code (rsync target)
  anchor.env                  # secrets, EnvironmentFile (chmod 600)
  requirements.txt  .venv/    # py3.8 venv: Flask, Jinja2, pycryptodome, gunicorn
  anchor.db                   # sqlite presence store (90s TTL rows)
  dist/                       # the two client zips + download.html (served by nginx)
```

- **Service:** `yaw-anchor.service` → gunicorn (1 worker, 4 threads) on
  `127.0.0.1:8055`. nginx proxies `/` → it (ProxyFix on, so the node's real IP is
  recorded, not nginx's).
- **nginx vhost:** `/etc/nginx/sites-available/<anchor-host>` (original backed up to
  `<anchor-host>.bak-pre-yaw`).

## Operations

```sh
# status / logs / restart  (magnus has passwordless sudo)
ssh magnus@<server-host> 'sudo systemctl status yaw-anchor --no-pager'
ssh magnus@<server-host> 'sudo journalctl -u yaw-anchor -n 50 --no-pager'
ssh magnus@<server-host> 'sudo systemctl restart yaw-anchor'

# redeploy anchor code after local changes
./deploy/redeploy.sh

# roll nginx back to the pre-YAW vhost
ssh magnus@<server-host> 'sudo cp /etc/nginx/sites-available/<anchor-host>.bak-pre-yaw \
  /etc/nginx/sites-available/<anchor-host> && sudo nginx -t && sudo systemctl reload nginx'
```

## Updating the client bundles

Rebuild (`electron-client/`), then upload into `dist/` (nginx serves them
directly):

```sh
cd electron-client
./node_modules/.bin/electron-packager . YAW --platform=darwin --arch=arm64 \
  --out=release --overwrite --asar --ignore="^/(release|test|tools|yawdata)($|/)"
# ...zip as in release/ ... then:
rsync -a release/yaw-*.zip fnlr@<server-host>:/home/fnlr/yaw-anchor/dist/
```
