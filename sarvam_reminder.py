import argparse
from base64 import b64decode
from dataclasses import dataclass
from tempfile import NamedTemporaryFile

from httpx import RequestError
from sarvamai import SarvamAI
from sarvamai.core.api_error import ApiError

from sarvam_client import create_sarvam_client


ENGLISH_REMINDER = (
    "Hello {name}, this is a reminder from {lender}. "
    "Your payment of {amount} rupees is due. If you need help, please contact us."
)
FALLBACK_REMINDERS = {
    "hi-IN": (
        "नमस्ते {name}, यह {lender} की ओर से एक याद दिलाने वाला संदेश है। "
        "आपका {amount} रुपये का भुगतान बाकी है। मदद चाहिए तो हमसे संपर्क करें।"
    ),
    "kn-IN": (
        "ನಮಸ್ಕಾರ {name}, ಇದು {lender} ಕಡೆಯಿಂದ ಒಂದು ಜ್ಞಾಪನೆ. "
        "ನಿಮ್ಮ {amount} ರೂಪಾಯಿ ಪಾವತಿ ಬಾಕಿಯಿದೆ. ಸಹಾಯ ಬೇಕಿದ್ದರೆ ನಮ್ಮನ್ನು ಸಂಪರ್ಕಿಸಿ."
    ),
}
SPEAKERS = {
    "hi-IN": "kavya_hi_conversational",
    "kn-IN": "chaitra_kn_conversation",
}
PROVIDER_ERRORS = (ApiError, RequestError, ValueError)


@dataclass(frozen=True)
class Reminder:
    text: str
    audio_base64: str | None
    used_template: bool


def generate_reminder(
    *, name: str, lender: str, amount: str, language: str, client: SarvamAI | None
) -> Reminder:
    """Return localized reminder text and optional base64 WAV audio."""
    if language not in FALLBACK_REMINDERS:
        raise ValueError("Level 1 supports hi-IN and kn-IN.")

    details = {"name": name, "lender": lender, "amount": amount}
    fallback = FALLBACK_REMINDERS[language].format(**details)
    if client is None:
        return Reminder(text=fallback, audio_base64=None, used_template=True)

    try:
        translation = client.text.translate(
            input=ENGLISH_REMINDER.format(**details),
            source_language_code="en-IN",
            target_language_code=language,
            model="sarvam-translate:v1",
        ).translated_text.strip()
    except PROVIDER_ERRORS:
        translation = ""

    text = translation or fallback
    try:
        speech = client.text_to_speech.convert(
            text=text,
            language_code=language,
            model="bulbul:v4-flash",
            speaker=SPEAKERS[language],
            output_audio_codec="wav",
        )
        audio = speech.audios[0] if speech.audios else None
        if audio:
            wav = b64decode(audio, validate=True)
            if not wav.startswith(b"RIFF") or wav[8:12] != b"WAVE":
                audio = None
    except PROVIDER_ERRORS:
        audio = None

    return Reminder(text=text, audio_base64=audio, used_template=not translation)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a sample borrower reminder.")
    parser.add_argument("language", choices=FALLBACK_REMINDERS)
    args = parser.parse_args()

    reminder = generate_reminder(
        name="Asha", lender="Demo Lending", amount="500",
        language=args.language, client=create_sarvam_client(),
    )
    print(reminder.text)
    if reminder.used_template:
        print("Translation unavailable. Used the local reminder template.")
    if reminder.audio_base64:
        with NamedTemporaryFile(prefix="luma-reminder-", suffix=".wav", delete=False) as wav:
            wav.write(b64decode(reminder.audio_base64))
        print(f"Audio saved to {wav.name}")
    else:
        print("Audio unavailable. The reminder text is still ready.")


if __name__ == "__main__":
    main()
