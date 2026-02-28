# Stream app.log to Google Cloud Logs Explorer

Run these in order. Steps 2–6 are on the VM (after you SSH in at Step 1).

---

## Prerequisites

- **IAM:** The VM’s service account must have permission to write logs. In **IAM & Admin** → **IAM**, add the VM’s service account (see VM details → **Service account**) with role **Logs Writer** (or Owner). If you get `Permission 'logging.logEntries.create' denied`, the account or role is missing.
- **Access scopes:** The VM must allow the Cloud Logging API. In **Compute Engine** → VM → **Edit** (with VM **stopped**), set **Access scopes** to **Allow full access to all Cloud APIs** (or **Set access for each API** and enable **Cloud Logging**). Save and start the VM again.
- **Optional:** Reserve a **static external IP** for the VM so the IP does not change on stop/start; update **GCP_VM_HOST** and any scripts if the IP changes.

---

## Step 1 — SSH into the VM

**Run on your local machine.**

```bash
ssh -i ~/deploy_key -o StrictHostKeyChecking=no sunnyakpatel@34.145.149.188
```

---

## Step 2 — Check that app.log exists

**Run on the VM.** (Any directory.)

```bash
ls -la ~/sentry-bridge/data/app.log
```

You should see the file. If not, find it:

```bash
find ~ -name "app.log" 2>/dev/null
```

---

## Step 3 — Download the Ops Agent install script

**Run on the VM.**

```bash
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
```

---

## Step 4 — Install the Ops Agent

**Run on the VM.**

```bash
sudo bash add-google-cloud-ops-agent-repo.sh --also-install
```

---

## Step 5 — Check the agent is running

**Run on the VM.**

```bash
sudo systemctl status google-cloud-ops-agent
```

You should see `active (running)`. If it’s already installed from before, that’s fine; continue to Step 6.

---

## Step 6 — Write the config for app.log

**Run on the VM.** This creates `/etc/google-cloud-ops-agent/config.yaml` with your app.log path.

```bash
sudo tee /etc/google-cloud-ops-agent/config.yaml << 'ENDOFFILE'
logging:
  receivers:
    sentry_bridge_app:
      type: files
      include_paths:
        - /home/sunnyakpatel/sentry-bridge/data/app.log
  service:
    pipelines:
      sentry_bridge_pipeline:
        receivers: [sentry_bridge_app]
ENDOFFILE
```

**If that file already existed** (e.g. you had other logging config), you may have overwritten it. To add app.log without removing existing config, use:

```bash
sudo nano /etc/google-cloud-ops-agent/config.yaml
```

Add the `sentry_bridge_app` receiver and `sentry_bridge_pipeline` pipeline under `logging:` and merge with any existing `receivers` and `service.pipelines`.

---

## Step 7 — Restart the Ops Agent

**Run on the VM.**

```bash
sudo systemctl restart google-cloud-ops-agent
```

---

## Step 8 — Confirm the agent is running again

**Run on the VM.**

```bash
sudo systemctl status google-cloud-ops-agent
```

Should show `active (running)`. If it failed, check:

```bash
sudo cat /var/log/google-cloud-ops-agent/subagents/logging-module.log
```

---

## Step 9 — Confirm app.log has content

**Run on the VM.**

```bash
tail -5 ~/sentry-bridge/data/app.log
```

If you see log lines, the agent can read them. Wait 1–2 minutes for them to show up in Logs Explorer.

---

## Step 10 — Open Logs Explorer

**In your browser.**

1. Go to **Google Cloud Console** → **Logging** → **Logs Explorer**.
2. Select project **sentry-bridge**.
3. Set time range to **Last 1 hour** (or more).
4. In the query box, paste:

```text
resource.type="gce_instance"
```

5. Click **Run query** (or press Enter).
6. To filter to app-style lines (brain, errors, strategy), use:

```text
resource.type="gce_instance" AND jsonPayload.message=~"brain|ERROR|strategy|executor"
```

7. The log line text is in **jsonPayload.message** (expand a row to see it).

---

## Troubleshooting

- **No logs in Logs Explorer:** Wait 2–3 minutes and refresh. Confirm `~/sentry-bridge/data/app.log` exists and has recent lines (`tail -5`).
- **Permission denied on app.log:** Run on VM: `chmod 644 ~/sentry-bridge/data/app.log`
- **Agent won’t start:** Check `sudo systemctl status google-cloud-ops-agent` and `sudo cat /var/log/google-cloud-ops-agent/subagents/logging-module.log`. Fix YAML in `/etc/google-cloud-ops-agent/config.yaml` and run Step 7 again.
- **Permission 'logging.logEntries.create' denied:** The VM’s service account needs **Logs Writer** in IAM (see Prerequisites). Also ensure **Access scopes** allow the Cloud Logging API (stop VM → Edit → **Allow full access to all Cloud APIs** or enable Cloud Logging → Save → Start). Then `sudo systemctl restart google-cloud-ops-agent`.
- **App log lines not in Logs Explorer:** Query `resource.type="gce_instance"` and expand entries; look for `jsonPayload.message` or `textPayload`. During market hours you’ll see brain/strategy lines; when the market is closed, app.log may have little new content.
