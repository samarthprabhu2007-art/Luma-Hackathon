import argparse
import json
import os
import re
import secrets
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from sarvam_client import create_sarvam_client
from sarvam_reminder import PROVIDER_ERRORS, SPEAKERS


LANGUAGES = {"hi-IN": "Hindi", "kn-IN": "Kannada", "ta-IN": "Tamil", "te-IN": "Telugu"}
AUDIO_FORMATS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4"}
PORT = 8765
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
TUNNEL_HOST = re.compile(r"[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)
PAGE = Path(__file__).with_suffix(".html")
TUNNEL_ENV = PAGE.with_name(".env")


def tunnel_password():
    value = os.environ.get("SARVAM_TUNNEL_PASSWORD")
    if value:
        return value
    if TUNNEL_ENV.is_file():
        for line in TUNNEL_ENV.read_text(encoding="utf-8-sig").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "SARVAM_TUNNEL_PASSWORD" and value.strip():
                return value.strip()
    raise SystemExit("Set SARVAM_TUNNEL_PASSWORD in testing/.env before enabling the tunnel.")


class ChatHandler(BaseHTTPRequestHandler):
    def send_result(self, status, payload, content_type="application/json; charset=utf-8"):
        body = json.dumps(payload, ensure_ascii=False).encode() if isinstance(payload, dict) else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if status == 401:
            self.send_header("WWW-Authenticate", 'Basic realm="Sarvam phone test"')
        self.end_headers()
        self.wfile.write(body)

    def allow_request(self):
        host = self.headers.get("Host", "")
        authorization = self.server.tunnel_authorization
        is_tunnel = authorization is not None and TUNNEL_HOST.fullmatch(host)
        if host not in HOSTS and not is_tunnel:
            self.send_result(403, {"error": "Unrecognized chat host."})
            return False

        if authorization is not None:
            provided = self.headers.get("Authorization", "").encode()
            if not secrets.compare_digest(provided, authorization):
                self.send_result(401, {"error": "Enter the phone-test credentials from PowerShell."})
                return False

        origin = self.headers.get("Origin")
        scheme = "https" if is_tunnel else "http"
        if origin and origin != f"{scheme}://{host}":
            self.send_result(403, {"error": "Open the chat from its own URL."})
            return False
        return True

    def do_GET(self):
        if not self.allow_request():
            return
        if self.path == "/":
            self.send_result(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        else:
            self.send_result(404, {"error": "Page not found."})

    def do_POST(self):
        if not self.allow_request():
            return
        address = urlsplit(self.path)
        is_audio = address.path == "/api/transcribe"
        is_speech = address.path == "/api/speak"
        if address.path not in {"/api/chat", "/api/transcribe", "/api/speak"}:
            self.send_result(404, {"error": "Page not found."})
            return

        try:
            limit = 4_000_000 if is_audio else 32_000
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= limit:
                raise ValueError("Message or recording is empty or too large.")
            body = self.rfile.read(length)
            if is_audio:
                language = parse_qs(address.query).get("language", [""])[0]
                mime = self.headers.get_content_type()
                codec = AUDIO_FORMATS.get(mime)
                if not codec:
                    raise ValueError("Unsupported recording format. Try Chrome or Edge.")
            else:
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError("Send a valid chat message.")
                language = data.get("language")
                message = data.get("message")
                limit = 2500 if is_speech else 1200
                if not isinstance(message, str) or not 0 < len(message.strip()) <= limit:
                    raise ValueError(f"Enter a message of 1 to {limit:,} characters.")
                history = data.get("history", [])
                if not isinstance(history, list):
                    raise ValueError("Invalid chat history.")
                if any(
                    not isinstance(turn, dict) or turn.get("role") not in ("user", "assistant")
                    or not isinstance(turn.get("content"), str)
                    for turn in history[-8:]
                ):
                    raise ValueError("Invalid chat history.")

            if not isinstance(language, str) or language not in LANGUAGES:
                raise ValueError("Choose a supported language.")
        except (ValueError, UnicodeError) as error:
            self.send_result(400, {"error": str(error)})
            return

        client = self.server.sarvam
        if client is None:
            self.send_result(503, {"error": self.server.sarvam_error})
            return

        try:
            if is_audio:
                result = client.speech_to_text.transcribe(
                    file=(f"recording.{codec}", body, mime),
                    model="saaras:v4", mode="transcribe",
                    language_code=language, input_audio_codec=codec,
                )
                transcript = result.transcript.strip()
                if not transcript:
                    self.send_result(422, {"error": "No speech detected. Try again or type your message."})
                    return
                self.send_result(200, {"text": transcript})
                return

            if is_speech:
                speech = client.text_to_speech.convert(
                    text=message.strip(), language_code=language, model="bulbul:v4-flash",
                    speaker=SPEAKERS[language], output_audio_codec="wav",
                    request_options={"timeout_in_seconds": 20, "max_retries": 0},
                )
                if speech.audios:
                    self.send_result(200, {"audio": speech.audios[0]})
                else:
                    self.send_result(424, {"error": "Sarvam returned no playable reply."})
                return

            messages = [{
                "role": "system",
                "content": f"Reply in {LANGUAGES[language]} in its native script. "
                "Use plain text and keep replies to two short sentences unless the user asks for more.",
            }]
            messages.extend(
                {"role": turn["role"], "content": turn["content"][:1200]} for turn in history[-8:]
            )
            messages.append({"role": "user", "content": message.strip()})
            completion = client.chat.completions(
                model="sarvam-105b", messages=messages, reasoning_effort=None, max_tokens=400,
                request_options={"timeout_in_seconds": 25, "max_retries": 0},
            )
            reply = (completion.choices[0].message.content or "").strip() if completion.choices else ""
            if not reply:
                self.send_result(424, {"error": "Sarvam returned an empty reply. Please try again."})
                return
        except PROVIDER_ERRORS as error:
            status = getattr(error, "status_code", None)
            detail = f" (HTTP {status})" if isinstance(status, int) else ""
            self.log_error("%s: %s%s", address.path, type(error).__name__, detail)
            self.send_result(424, {"error": f"Sarvam could not complete the request{detail}. Try again."})
            return

        self.send_result(200, {"text": reply})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Sarvam testing UI.")
    parser.add_argument("--tunnel", action="store_true", help="Enable password-protected Cloudflare access.")
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", PORT), ChatHandler) as server:
        server.tunnel_authorization = None
        if args.tunnel:
            password = tunnel_password()
            server.tunnel_authorization = b"Basic " + b64encode(f"demo:{password}".encode())
            print("Phone test login: demo and the password in testing/.env.", flush=True)
        server.sarvam_error = "Set SARVAM_API_KEY in .env, then restart the app."
        try:
            server.sarvam = create_sarvam_client()
        except ImportError:
            server.sarvam = None
            server.sarvam_error = (
                "Sarvam could not use this terminal's proxy. "
                "Restart the app from the PowerShell window where Sarvam worked."
            )
        print(f"Open http://127.0.0.1:{PORT}", flush=True)
        server.serve_forever()
