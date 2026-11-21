from sarvam_client import create_sarvam_client

client = create_sarvam_client()
if client is None:
    raise SystemExit("Set SARVAM_API_KEY in .env first.")

reply = client.chat.completions(
    model="sarvam-105b",
    messages=[{"role": "user", "content": "Reply with only the word Namaste."}],
)
print(reply.choices[0].message.content)
