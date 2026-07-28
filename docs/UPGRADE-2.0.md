# Upgrade runbook: soulseek-web 1.1.0 → 2.0.0

Target: an existing **Linux / systemd** install (Proxmox LXC, Debian or Ubuntu), created by
`install.sh` and living at `/opt/soulseek-web`.

Written to be executed step by step. Every step has a check; if a check fails, stop and go to
[Rollback](#rollback).

---

## 0. Before you start

**Prerequisite:** version 2.0.0 must be on the `main` branch of
`https://github.com/sgutierrezbe/soulseek-web`. Verify before touching the container:

```bash
git ls-remote https://github.com/sgutierrezbe/soulseek-web.git main
curl -s https://raw.githubusercontent.com/sgutierrezbe/soulseek-web/main/VERSION
# must print 2.0.0
```

If that prints `1.1.0`, the release has not been published yet — **stop here**.

### What this upgrade does *not* change

You do **not** need to touch any of these, and should not:

- **slskd.** Its config, API key, port and download directory are untouched. soulseek-web talks to
  it exactly as before. (2.0.0 fixes an `api_keys` YAML bug, but only in the *Windows standalone*
  installer, which does not apply here.)
- **`credentials.json`.** The format is backwards compatible and is read in place. Do not delete
  or migrate it.
- **The systemd unit.** Still `uvicorn main:app` on port 8080. `install.sh` rewrites it with
  identical content.
- **Your reverse proxy / firewall / port mapping.** Still one HTTP service on 8080.
- **The music folder.** Same path, same layout.

### What is new that you should know about

| Change | Impact |
|---|---|
| New writable dir `/opt/soulseek-web/.cache` | Cover-art cache. Grows to ~256 MB max. Needs write access for the service user. |
| Dependencies are now pinned, and `uvicorn[standard]` is used | The venv must be re-synced. See step 4 note if the build fails. |
| Static assets moved out of `index.html` into `/static/` | Nothing to do; served by the same process. |
| New `/health` endpoint | Useful for your monitoring. Returns app + slskd status. |
| Optional password auth (`AUTH_PASSWORD`) | Off by default; behaviour unchanged unless you set it. |
| Python 3.11+ required | Same as 1.1.0. Confirm in step 1 anyway. |

---

## 1. Pre-flight

Run inside the container.

```bash
cd /opt/soulseek-web

# Confirm this is the install we think it is
systemctl is-active soulseek-web
cat VERSION                       # expect 1.1.0
git rev-parse --short HEAD        # note this value — you need it to roll back
python3 --version                 # must be 3.11 or newer
df -h /opt                        # need ~500 MB free (deps + cover cache)
```

Record the current commit hash. Call it `$OLD_COMMIT` below.

Confirm there are no local edits that would block a pull:

```bash
git status --porcelain
```

Expected output: **empty**. `credentials.json` is gitignored and will not appear.
If anything is listed, someone edited the install by hand — capture it before continuing:

```bash
git diff > /root/soulseek-web-local-changes.patch
git stash
```

## 2. Back up

Cheap and makes rollback trivial. Do not skip.

```bash
tar czf /root/soulseek-web-backup-$(date +%F).tar.gz \
  -C /opt soulseek-web --exclude='soulseek-web/venv' --exclude='soulseek-web/.cache'
ls -lh /root/soulseek-web-backup-*.tar.gz
```

If this container is a Proxmox VM/CT you can also just take a snapshot from the host, which is
faster to restore:

```bash
# on the Proxmox host, replace <CTID>
pct snapshot <CTID> pre-slskweb-2
```

## 3. Stop the service

```bash
systemctl stop soulseek-web
```

## 4. Update the code and dependencies

The supported path is to re-run the installer — it pulls, re-syncs the venv, rewrites the unit
file, and restarts:

```bash
curl -sSL https://raw.githubusercontent.com/sgutierrezbe/soulseek-web/main/install.sh | sudo bash
```

<details>
<summary>Or do it manually, if you prefer to see each step</summary>

```bash
cd /opt/soulseek-web
git pull --ff-only
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
systemctl restart soulseek-web
```
</details>

> **If `pip install` fails building `uvloop` or `httptools`** (happens on unusual architectures
> without prebuilt wheels), install the plain server instead — the app runs identically, just
> without the optional speedups:
>
> ```bash
> venv/bin/pip install "uvicorn==0.51.0"
> ```

**Check:**

```bash
cat /opt/soulseek-web/VERSION     # expect 2.0.0
```

## 5. Permissions for the new cache directory

The stock `install.sh` unit runs as root, in which case this is already fine. If you changed the
unit to run as a non-root user, give that user write access:

```bash
# only if your unit has a User= line — substitute the actual user
install -d -o soulseek -g soulseek /opt/soulseek-web/.cache
```

To put the cache somewhere else (e.g. off a small root disk), add to the unit and reload:

```
Environment=CACHE_DIR=/var/cache/soulseek-web
```

## 6. Start and verify

```bash
systemctl start soulseek-web
systemctl status soulseek-web --no-pager
```

Work through all of these. They take about a minute.

```bash
# 1. Service is healthy and can see slskd
curl -s localhost:8080/health
#    expect: {"status":"ok","version":"2.0.0",...,"slskd":"ok"}
#    if "slskd":"unreachable", the connection settings did not carry over — see Troubleshooting

# 2. Existing settings were preserved (should show your real slskd URL and music path)
curl -s localhost:8080/api/setup/status

# 3. The new split assets are served
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/static/css/app.css
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/static/js/app.js
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/manifest.webmanifest
#    all three: 200

# 4. Library scan sees your downloads (new in 2.0.0; [] means MUSIC_PATH is wrong or empty)
curl -s localhost:8080/api/library/albums | head -c 300

# 5. No errors in the log
journalctl -u soulseek-web -n 40 --no-pager
```

Then in a browser, from a phone if possible:

1. Open `http://<container-ip>:8080` — you should get the new dark UI with a **four**-tab bottom
   nav (Search / Downloads / Library / Settings). Three tabs means the browser is serving a
   cached old page; hard-refresh.
2. Run a search. Results should appear within a few seconds.
3. Open **Downloads** — any in-flight transfers should show progress, speed and ETA.
4. Open **Library** — your downloaded albums should be listed. Tap one and press play.
5. Open **Settings** — confirm the slskd URL, API key and music folder are the values you had.

## 7. Optional post-upgrade steps

**Set a password.** Only meaningful if this is reachable beyond your LAN. Either in
Settings → Security, or in the unit file:

```
Environment=AUTH_PASSWORD=<a long random string>
```

Then `systemctl daemon-reload && systemctl restart soulseek-web`.

**Pin a session secret** so logins survive restarts (otherwise a restart logs everyone out):

```
Environment=SESSION_SECRET=<openssl rand -hex 32>
```

**Add a healthcheck to your monitoring:** `GET /health`, expect HTTP 200 and `.status == "ok"`.
Note it returns 200 even when slskd is down — alert on `.slskd != "ok"` if you want that covered.

---

## Rollback

Works at any point. Takes under a minute.

```bash
systemctl stop soulseek-web
cd /opt/soulseek-web
git checkout $OLD_COMMIT          # the hash recorded in step 1
venv/bin/pip install -r requirements.txt
systemctl start soulseek-web
curl -s localhost:8080/health
```

If the working tree is damaged, restore the tarball instead:

```bash
systemctl stop soulseek-web
mv /opt/soulseek-web /opt/soulseek-web.broken
tar xzf /root/soulseek-web-backup-<date>.tar.gz -C /opt
cd /opt/soulseek-web && python3 -m venv venv && venv/bin/pip install -r requirements.txt
systemctl start soulseek-web
```

`credentials.json` is untouched by either path, so settings survive a rollback.

---

## Troubleshooting

**`/health` says `"slskd":"unreachable"`.**
Settings did not carry over, or slskd is genuinely down. Check in order:

```bash
cat /opt/soulseek-web/credentials.json     # slskd_url and slskd_api_key present?
curl -s -H "X-API-Key: <key>" <slskd_url>/api/v0/application
```

If the second command fails, the problem is slskd or the key, not this upgrade.

**Service won't start, log shows `ModuleNotFoundError`.**
The venv did not re-sync. Run `venv/bin/pip install -r requirements.txt` and restart.

**Service won't start, log shows a permissions error on `credentials.json` or `.cache`.**
See step 5.

**UI loads but is unstyled, or the browser shows the old three-tab layout.**
A cached page. 2.0.0 stamps asset URLs with the version so this should self-correct on reload;
force it with Ctrl-Shift-R. On a phone that previously had the site open, close the tab and
reopen. There is no service worker in 1.1.0, so there is no stale worker to unregister.

**Library tab is empty.**
`MUSIC_PATH` points somewhere the service cannot read, or the folder has no audio files.
Check the path in Settings, and that the service user can read it:

```bash
sudo -u root ls -la "$(python3 -c "import json;print(json.load(open('/opt/soulseek-web/credentials.json'))['music_path'])")"
```

**Search returns "Could not reach slskd" where 1.1.0 showed an empty list.**
This is intentional. 1.1.0 swallowed connection errors and rendered zero results; 2.0.0 reports
them. The underlying problem was there before — fix the slskd connection.

---

## Appendix: moving to Docker instead

Optional. Only worth doing if you would rather manage this as a container than a systemd service.
It replaces the whole install, so keep the backup.

```bash
git clone https://github.com/sgutierrezbe/soulseek-web.git /opt/soulseek-web-docker
cd /opt/soulseek-web-docker
cp .env.example .env
# Set SOULSEEK_USERNAME / SOULSEEK_PASSWORD / SLSKD_API_KEY / MUSIC_PATH.
# MUSIC_PATH must be the same host path your current install uses.
docker compose up -d
```

Note this compose file brings up **its own slskd**. If you already run slskd elsewhere, delete the
`slskd` service block from `docker-compose.yml` and point `SLSKD_URL` at the existing one, or you
will have two daemons fighting over the same Soulseek account — Soulseek allows only one login per
account at a time.

Stop the old service first: `systemctl disable --now soulseek-web`.
