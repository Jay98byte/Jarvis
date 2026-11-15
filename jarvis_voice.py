"""
jarvis_voice.py - Live Speech Recognition & Audio Response Loop
Listens continuously through your microphone, processes commands, and speaks back.
"""

import sys
import subprocess
import time
import re
import speech_recognition as sr
import jarvis_brain

LISTEN_PAUSE_THRESHOLD = 3.0
LISTEN_PHRASE_TIME_LIMIT = 30
LISTEN_NON_SPEAKING_DURATION = 1.0
LISTEN_ENERGY_RATIO = 1.2


def configure_recognizer(recognizer, pause_threshold=None):
    pause_threshold = (
        LISTEN_PAUSE_THRESHOLD
        if pause_threshold is None
        else float(pause_threshold)
    )
    recognizer.dynamic_energy_threshold = True
    recognizer.dynamic_energy_ratio = LISTEN_ENERGY_RATIO
    recognizer.pause_threshold = pause_threshold
    recognizer.non_speaking_duration = min(
        LISTEN_NON_SPEAKING_DURATION, pause_threshold
    )


class _SoundDeviceStream:
    def __init__(self, stream):
        self._stream = stream

    def read(self, frames):
        audio, _overflowed = self._stream.read(frames)
        return bytes(audio)

    def close(self):
        try:
            self._stream.stop()
        finally:
            self._stream.close()


class SoundDeviceMicrophone(sr.AudioSource):
    SAMPLE_RATE = 16000
    SAMPLE_WIDTH = 2
    CHUNK = 1024

    def __init__(self, sounddevice, device=None):
        self._sounddevice = sounddevice
        self.device = device
        self.stream = None

    def __enter__(self):
        if self.stream is not None:
            raise RuntimeError("Microphone source is already open.")
        raw_stream = self._sounddevice.RawInputStream(
            samplerate=self.SAMPLE_RATE,
            blocksize=self.CHUNK,
            channels=1,
            dtype="int16",
            device=self.device,
        )
        try:
            raw_stream.start()
        except Exception:
            raw_stream.close()
            raise
        self.stream = _SoundDeviceStream(raw_stream)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.stream.close()
        finally:
            self.stream = None


def _create_microphone():
    try:
        import sounddevice
    except ImportError:
        try:
            return sr.Microphone()
        except Exception as pyaudio_error:
            raise RuntimeError(
                "No microphone backend is available. Install project requirements "
                "to enable sounddevice, or install PyAudio."
            ) from pyaudio_error
    return SoundDeviceMicrophone(sounddevice)


def speak(text, enabled=True, rate=0, print_output=True):
    """Print a response and wait for the speech engine to finish speaking it."""
    if not text:
        return
    if print_output:
        print(f"\n[JARVIS]: {text}\n")
    if not enabled:
        return
    if sys.platform == "darwin":
        subprocess.run(["say", "-v", "Samantha", text])
    elif sys.platform == "win32":
        rate = max(-10, min(10, int(rate)))
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$reader = [System.IO.StreamReader]::new("
            "[Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8); "
            "$text = $reader.ReadToEnd(); "
            "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$preferredVoice = $speaker.GetInstalledVoices() | "
            "Where-Object { $_.Enabled -and $_.VoiceInfo.Name -eq 'Microsoft David Desktop' } | "
            "Select-Object -First 1; "
            "if ($preferredVoice) { $speaker.SelectVoice($preferredVoice.VoiceInfo.Name) }; "
            f"$speaker.Rate = {rate}; "
            "try { $speaker.Speak($text) } finally { $speaker.Dispose() }"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=180,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode:
                details = (
                    result.stderr.decode("utf-8", errors="replace").strip()
                    or result.stdout.decode("utf-8", errors="replace").strip()
                )
                print(f"[Speech output error] Windows speech exited with code "
                      f"{result.returncode}: {details}")
        except (OSError, subprocess.SubprocessError) as e:
            print(f"[Speech output error] Could not run Windows speech: {e}")
    else:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", max(80, min(350, 200 + int(rate) * 10)))
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"[Speech output error]: {e}")


def _is_shutdown_command(query):
    normalized = re.sub(r"[\W_]+", " ", query.lower()).strip()
    if normalized.startswith("jarvis "):
        normalized = normalized[len("jarvis "):]
    return normalized in ("cooldown", "cool down")


def listen_loop():
    recognizer = sr.Recognizer()
    configure_recognizer(recognizer)

    try:
        mic = _create_microphone()
    except Exception as e:
        print(f"Error accessing microphone: {e}")
        print("Falling back to text console input mode.")
        while True:
            try:
                user_input = input("You: ")
                if user_input.strip():
                    if _is_shutdown_command(user_input):
                        print("Cooling down. Shutting down Jarvis.")
                        break
                    reply = jarvis_brain.think(user_input)
                    speak(reply)
            except (KeyboardInterrupt, EOFError):
                break
        return

    try:
        with mic as source:
            print("\n" + "=" * 50)
            print("  JARVIS AI ASSISTANT IS ACTIVE AND LISTENING")
            print("  Say commands like:")
            print("    - 'Jarvis, open VS Code'")
            print("    - 'Play Blinding Lights on Spotify'")
            print("    - 'Play lofi on YouTube'")
            print("    - 'Stock market update' / 'Analyze Nifty'")
            print("    - 'Send WhatsApp message'")
            print("    - 'Read unread emails'")
            print("=" * 50 + "\n")
            recognizer.adjust_for_ambient_noise(source, duration=1.0)
    except Exception as e:
        print(f"Error opening microphone: {e}")
        print("Check Windows microphone permissions and the selected input device.")
        print("Falling back to text console input mode.")
        while True:
            try:
                user_input = input("You: ")
                if user_input.strip():
                    if _is_shutdown_command(user_input):
                        print("Cooling down. Shutting down Jarvis.")
                        break
                    reply = jarvis_brain.think(user_input)
                    speak(reply)
            except (KeyboardInterrupt, EOFError):
                break
        return

    try:
        with mic as source:
            while True:
                try:
                    print("Listening... ", end="", flush=True)
                    audio = recognizer.listen(
                        source, timeout=10, phrase_time_limit=LISTEN_PHRASE_TIME_LIMIT,
                    )
                    print("Processing... ", end="", flush=True)

                    query = recognizer.recognize_google(audio).strip()
                    print(f"\nYou said: \"{query}\"")

                    q_clean = query.lower()
                    if "jarvis" in q_clean:
                        q_clean = q_clean.replace("jarvis", "").strip(" ,.!?")

                    if not q_clean:
                        speak("Yes sir, I'm listening.")
                        continue

                    if _is_shutdown_command(q_clean):
                        print("Cooling down. Shutting down Jarvis.")
                        break

                    response = jarvis_brain.think(q_clean)
                    speak(response)

                except sr.WaitTimeoutError:
                    continue
                except sr.UnknownValueError:
                    continue
                except KeyboardInterrupt:
                    print("\nShutting down Jarvis. Goodbye!")
                    break
                except Exception as e:
                    print(f"\n[Notice]: {e}")
                    time.sleep(0.5)
    except Exception as e:
        print(f"Microphone stream failed: {e}")
        return


if __name__ == "__main__":
    import jarvis_desktop

    jarvis_desktop.main()
