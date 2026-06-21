# YAW anchor — deployment (fnlr.se)

The rendezvous anchor runs on **emop.se** (host `survey.emop.se`, Ubuntu, Python
3.8) as the `fnlr` user, behind nginx with the existing Let's Encrypt cert that
already covers `fnlr.se`. The public site shows only an innocuous cover page; the
directory API and the client download live under unguessable paths.

## Live URLs

| What | URL |
|------|-----|
| Public cover page | `https://fnlr.se/` |
| **Client anchor URL** (baked into the client) | `https://fnlr.se/4d6553fef88e` |
| Operator status page | `https://fnlr.se/4d6553fef88e/status` |
| **Secret download link** | `https://fnlr.se/5f0813a105c5acab/` |

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
- **nginx vhost:** `/etc/nginx/sites-available/fnlr.se` (original backed up to
  `fnlr.se.bak-pre-yaw`).

## Operations

```sh
# status / logs / restart  (magnus has passwordless sudo)
ssh magnus@emop.se 'sudo systemctl status yaw-anchor --no-pager'
ssh magnus@emop.se 'sudo journalctl -u yaw-anchor -n 50 --no-pager'
ssh magnus@emop.se 'sudo systemctl restart yaw-anchor'

# redeploy anchor code after local changes
./deploy/redeploy.sh

# roll nginx back to the pre-YAW vhost
ssh magnus@emop.se 'sudo cp /etc/nginx/sites-available/fnlr.se.bak-pre-yaw \
  /etc/nginx/sites-available/fnlr.se && sudo nginx -t && sudo systemctl reload nginx'
```

## Updating the client bundles

Rebuild (`electron-client/`), then upload into `dist/` (nginx serves them
directly):

```sh
cd electron-client
./node_modules/.bin/electron-packager . YAW --platform=darwin --arch=arm64 \
  --out=release --overwrite --asar --ignore="^/(release|test|tools|yawdata)($|/)"
# ...zip as in release/ ... then:
rsync -a release/yaw-*.zip fnlr@emop.se:/home/fnlr/yaw-anchor/dist/
```
