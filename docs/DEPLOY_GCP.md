# Deploy Sentry Bridge to GCP

This guide covers:

1. One-time VM setup (Docker, clone repo, `.env`).
2. GitHub Actions: **merge/push to main** = build image and push to ghcr.io only; **manual trigger** = build and deploy to VM (pull + run; no build on VM).
3. Where to find values and how to add GitHub secrets.

---

## Part 1: One-time VM setup

### 1.1 Create a GCP VM

- **Compute Engine** → **VM instances** → **Create instance**.
- Choose **Ubuntu 22.04** or **Debian**; e2-standard-2 or e2-standard-4 recommended.
- Allow **HTTP/HTTPS** if needed; SSH (port 22) is usually enabled by default.
- Note the **External IP** after creation (e.g. `34.145.173.89`)—this is **GCP_VM_HOST**.

### 1.2 SSH in and install Docker

SSH via the GCP Console (**Connect** → **SSH**) or from your machine: `ssh USER@EXTERNAL_IP`.

**Ubuntu:**

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

**Debian:** Use the same steps but replace `ubuntu` with `debian` in the `curl` and `echo` URLs. Then:

```bash
sudo usermod -aG docker "$USER"
```

Log out and SSH back in (or run `newgrp docker`).

### 1.3 Clone repo and configure `.env`

```bash
cd ~
git clone https://github.com/YOUR_ORG/sentry-bridge.git
cd sentry-bridge
cp .env.example .env
nano .env
```

Set at least: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `ACTIVE_SYMBOLS_FILE=data/active_symbols.txt`, `OPPORTUNITY_ENGINE_ENABLED=true`, `SCREENER_UNIVERSE=lab_12`. Do **not** set `REDIS_URL` or `BRAIN_CMD`. Save and exit.

### 1.4 First run (optional)

If you will use the workflow (Part 2), run it **manually** once to pull the image and start the stack—you can skip building on the VM. Otherwise:

```bash
docker compose up -d --build
```

(Requires enough disk; the image is large.) Then: `docker compose ps` and `docker compose logs -f app`.

### 1.5 Enable Docker on boot (optional)

```bash
sudo systemctl enable docker
```

---

## Part 2: GitHub Actions — build on push, deploy on manual trigger

- **Merge or push to main:** workflow **only builds** the image and pushes to **ghcr.io**. The deploy job does **not** run (no SSH to VM).
- **Manual trigger (Actions → Deploy to GCP VM → Run workflow):** workflow **builds** the image, pushes to ghcr.io, **and deploys** to the VM (`git` update, `docker compose pull`, `docker compose up -d`). No build on the VM.

### 2.1 Create deploy SSH key (on your Mac/laptop)

```bash
cd ~
ssh-keygen -t ed25519 -C "github-actions-deploy" -f deploy_key -N ""
```

This creates `deploy_key` (private) and `deploy_key.pub` (public).

### 2.2 Add public key to the VM

Use the **same user** that runs Docker (e.g. `sunnyakpatel` or `sunnypatel`). Choose one:

**Option A – GCP Console (recommended; key persists across reboots):**

1. GCP Console → **Compute Engine** → **VM instances** → click your VM → **Edit** (pencil).
2. Scroll to **SSH Keys** → **+ Add item**.
3. Paste the **entire line** from `cat ~/deploy_key.pub` (e.g. `ssh-ed25519 AAAA... github-actions-deploy`).
4. Save. The key is stored in instance metadata; the VM will keep it in `~/.ssh/authorized_keys` even after reboots.

**Option B – From your machine (if you can already SSH to the VM):**

```bash
ssh-copy-id -i ~/deploy_key.pub YOUR_VM_USER@EXTERNAL_IP
```

**Option C – Manual (on the VM):** On your machine run `cat ~/deploy_key.pub` and copy the line. SSH into the VM, then:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "PASTE_THE_LINE_FROM_deploy_key.pub" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Note: If you use Option C, GCP’s metadata agent may overwrite `authorized_keys` on reboot; use Option A so the key is in metadata and persists.

### 2.3 Add GitHub repository secrets

1. Open your repo on GitHub → **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** for each of the following.

| Secret name | Where to get the value |
|-------------|------------------------|
| **GCP_VM_HOST** | GCP Console → **Compute Engine** → **VM instances** → your VM → **External IP** column (e.g. `34.145.173.89`). |
| **GCP_VM_USER** | The Linux username you use to SSH (e.g. `ubuntu`, `sunnyakpatel`). It appears in your SSH prompt: `user@hostname`. |
| **GCP_SSH_PRIVATE_KEY** | On your machine run `cat ~/deploy_key` and paste the **entire** output, including `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----`. |
| **GHCR_PAT** | GitHub → your profile **Settings** → **Developer settings** → **Personal access tokens** → create a token with **read:packages** (so the VM can pull the image from ghcr.io). Paste the token as the secret value. |
| **GCP_REPO_PATH** (optional) | Path to the repo on the VM if not `~/sentry-bridge` (e.g. `/home/sunnyakpatel/sentry-bridge`). |

### 2.4 Trigger the workflow

- **Merge or push to main:** Workflow runs and **only builds** the image, then pushes to `ghcr.io/<owner>/<repo>/sentry-bridge-app:latest`. The **Deploy on VM** job is **skipped** (no SSH).
- **Manual trigger:** In the repo go to **Actions** → **Deploy to GCP VM** → **Run workflow** → **Run workflow**. That run **builds** the image, pushes to ghcr.io, **and deploys** to the VM (SSH, `git fetch` / `git reset --hard origin/main`, `docker login` ghcr.io, `docker compose pull`, `docker compose up -d`).

---

## Quick reference

| Step | What |
|------|------|
| GCP_VM_HOST | Compute Engine → VM instances → External IP |
| GCP_VM_USER | SSH username (e.g. from prompt `user@host`) |
| GCP_SSH_PRIVATE_KEY | Full contents of `deploy_key` (you generate it) |
| GHCR_PAT | GitHub PAT with `read:packages` |
| Public key | Add `deploy_key.pub` to VM `~/.ssh/authorized_keys` |

See also the main [README](../README.md) for app configuration and local run.
