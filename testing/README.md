# Sarvam chat UI

Complete [team setup](../requirements.md) first, then run this from the project root:

```powershell
python -m testing.sarvam_chat_ui
```

Open [the local chat](http://127.0.0.1:8765) in Chrome or Edge. Choose Hindi, Kannada, Tamil, or Telugu. Type a message or record a short one, review the transcript, then send it. Use the audio player below Sarvam's reply to hear it.

This page sends typed messages and microphone recordings to Sarvam to test the conversation. Use sample input. The API key is loaded by the local Python server.

## Test from a phone

Stop the local-only runner with Ctrl+C, then run this from the project in your regular PowerShell:

```powershell
python -m testing.sarvam_chat_ui --tunnel
```

Keep it running. In a second PowerShell, run:

```powershell
cloudflared tunnel --url http://127.0.0.1:8765
```

Open the printed HTTPS URL on your phone. Sign in as `demo` with the password configured in `testing/.env` as `SARVAM_TUNNEL_PASSWORD`, then allow microphone access when prompted. Stop the tunnel with Ctrl+C when finished.
