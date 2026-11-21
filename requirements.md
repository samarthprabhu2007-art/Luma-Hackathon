# Team setup

Run the commands below from the `Luma-Hackathon` directory.

## Install

- Python 3 with pip
- Sarvam Python SDK

```powershell
python -m pip install sarvamai
```

## Configure Sarvam

1. Ask Samarth directly on WhatsApp for the Sarvam API key.
2. Create or open `.env` in the repo root. Paste the key immediately after `SARVAM_API_KEY=`.

   ```dotenv
   SARVAM_API_KEY=
   ```

3. Save the file locally. Keep `.env` and the API key out of Git.

## Check the setup

```powershell
python sarvam_chat.py
```

The script makes one chat completion request and prints the reply. It asks the model to reply with “Namaste.”

## Test the Level 1 reminder

```powershell
python -X utf8 sarvam_reminder.py hi-IN
python -X utf8 sarvam_reminder.py kn-IN
python -X utf8 sarvam_reminder.py ta-IN
python -X utf8 sarvam_reminder.py te-IN
```

Each command uses a made-up borrower, prints the localized reminder, and shows the path to the WAV file when audio succeeds. Open the WAV file to check playback. If Sarvam is unavailable, the command reports which fallback it used.

The app can call `generate_reminder` from `sarvam_reminder.py` with the borrower name, lender, formatted amount in rupees, language code, and the client returned by `create_sarvam_client()`. The result contains the reminder text, optional base64 WAV audio, and whether it used the local template.

## Optional phone testing

- Install [Cloudflare's `cloudflared` CLI](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/#windows) on the computer running the testing UI. Verify it with `cloudflared --version`.
- Create `testing/.env` and set `SARVAM_TUNNEL_PASSWORD` to your test password. The phone login username is `demo`. Keep this file out of Git.
- Open the tunnel's HTTPS link in a browser on your phone and allow microphone access.

See [the testing UI instructions](testing/README.md) for the Python and tunnel commands. Local chat and reminder tests only need the Sarvam SDK.
