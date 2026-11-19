"""Core assistant engine. Network AI features require a configured provider/gateway."""
from __future__ import annotations
import os, sys, json, time, uuid, re, threading, hashlib, hmac, subprocess, webbrowser
from pathlib import Path

try:
    import certifi
except ImportError:
    certifi = None
try:
    import requests
except ImportError:
    requests = None
try:
    import speech_recognition as sr
except ImportError:
    sr = None
try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

from security_firewall import SelfHealingShield, dpapi_protect, dpapi_unprotect
from jarvis_meta_brain import SovereignMetaBrain
from omniverse_tools import (
    human_type, human_click, press_hotkey, open_url, generate_ai_image,
    generate_sovereign_video, inspect_and_modify_file, ue5_remote_execute,
    create_3d_game_project, background_prepare_checkout, run_system_command,
)

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
PROFILE_PATH = os.path.join(BASE_DIR, "jarvis_profile.dat")
CREATIONS_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "JARVIS_Creations")
os.makedirs(CREATIONS_DIR, exist_ok=True)

SYSTEM_PROMPT = (
    "You are AETHER, a helpful desktop AI assistant. Answer clearly and accurately. "
    "Do not claim to have performed an action unless it was actually performed. "
    "Never output executable code for the desktop app to run."
)


class WebAccountBridge:
    """Optional Supabase account sync. Requires a correctly configured Supabase project."""
    def __init__(self, profile, save_cb, log_cb):
        self.profile, self.save_cb, self.log_cb = profile, save_cb, log_cb
        self.username = profile.get("web_username", "")
        self.user_id = profile.get("web_user_id", "")
        self.processed_cmd_ids = set()

    def is_connected(self):
        return bool(self.user_id and self.username)

    def disconnect(self):
        self.username = self.user_id = ""
        self.profile.pop("web_username", None)
        self.profile.pop("web_user_id", None)
        self.save_cb()

    def connect(self, username, password, create_if_missing=True):
        # Credentials are intentionally not sent anywhere unless endpoint and key are configured.
        endpoint = os.getenv("JARVIS_SUPABASE_URL", "").rstrip("/")
        key = os.getenv("JARVIS_SUPABASE_KEY", "")
        if not endpoint or not key or requests is None:
            return False, "Configure JARVIS_SUPABASE_URL and JARVIS_SUPABASE_KEY first."
        clean_user = re.sub(r"[^a-z0-9._-]", "", (username or "").strip().lower())
        if not clean_user or len(password or "") < 8:
            return False, "Enter a valid username and a password of at least 8 characters."
        headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            r = requests.get(f"{endpoint}/rest/v1/jarvis_accounts",
                params={"username": f"eq.{clean_user}", "select": "id,username,password_hash"},
                headers=headers, timeout=10)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                return False, "Account not found. Account creation must be configured in your Supabase project."
            # Legacy schema compatibility; password storage should be migrated server-side to a password auth provider.
            digest = hashlib.sha256(f"JARVIS_100L::{clean_user}::{password}".encode()).hexdigest()
            if not hmac.compare_digest(str(rows[0].get("password_hash", "")), digest):
                return False, "Incorrect password."
            self.username, self.user_id = clean_user, str(rows[0]["id"])
            self.profile.update(web_username=self.username, web_user_id=self.user_id)
            self.save_cb()
            return True, f"Connected as {self.username}."
        except Exception as exc:
            return False, f"Account connection failed: {exc}"

    def poll_remote_commands(self, execute_cb):
        # Remote command execution is deliberately disabled: polling untrusted cloud commands
        # and running them locally would be an unsafe remote-code-execution path.
        return


class CoupleBridge:
    """Local invite-code helper; pairing is not represented as a verified remote connection."""
    def __init__(self, profile, save_cb, speak_cb, log_cb, sign_fn=None):
        self.profile, self.save_cb = profile, save_cb
        if "my_couple_code" not in profile:
            profile["my_couple_code"] = f"LOVE-{uuid.uuid4().hex[:6].upper()}"
            save_cb()
        self.my_code = profile["my_couple_code"]
        self.partner_code = profile.get("partner_couple_code", "")

    def send_or_accept_invite(self, partner_code_input):
        code = (partner_code_input or "").strip().upper()
        if not code or code == self.my_code:
            return "Enter a valid partner code."
        return "Invite code recorded locally only. A backend pairing service is not configured."

    def check_status(self):
        return bool(self.partner_code), "Local-only; no server pairing configured"


class JarvisEngine:
    def __init__(self, firewall: SelfHealingShield, output_cb=None, state_cb=None, ui_cb=None):
        self.firewall, self.output_cb, self.state_cb, self.ui_cb = firewall, output_cb, state_cb, ui_cb
        self.tts_lock = threading.Lock()
        self.tts = None
        self.recognizer = sr.Recognizer() if sr else None
        self.voice_active = self.enrolling_now = False
        self.pending_payment_code = self.last_created_file = self.attached_file_path = None
        self.chat_history, self.global_skills = [], {}
        self.profile = self.load_profile()
        self.assistant_name = self.profile.get("assistant_name", "AETHER")
        self.active_mode = self.profile.get("active_mode", "GOD")
        self.preferred_model = self.profile.get("preferred_model", "AUTO")
        self.is_developer = bool(self.profile.get("is_developer", False))
        self.is_lifetime = bool(self.profile.get("is_lifetime", False))
        self.trial_start = float(self.profile.get("trial_start", time.time()))
        self.meta_brain = SovereignMetaBrain(self.profile, self.firewall.sign_cloud_request)
        self.web_bridge = WebAccountBridge(self.profile, self.save_profile, self.show_output)
        self.couple_bridge = CoupleBridge(self.profile, self.save_profile, self.speak, self.show_output, self.firewall.sign_cloud_request)

    def load_profile(self):
        if os.path.exists(PROFILE_PATH):
            try:
                with open(PROFILE_PATH, "rb") as f:
                    value = json.loads(dpapi_unprotect(f.read()).decode("utf-8"))
                if isinstance(value, dict):
                    return value
            except Exception:
                pass
        data = {"assistant_name": "AETHER", "active_mode": "GOD", "trial_start": time.time()}
        self.profile = data
        self.save_profile()
        return data

    def save_profile(self, data=None):
        if data is not None:
            self.profile = data
        try:
            os.makedirs(os.path.dirname(PROFILE_PATH), exist_ok=True)
            temp = PROFILE_PATH + ".tmp"
            with open(temp, "wb") as f:
                f.write(dpapi_protect(json.dumps(self.profile, indent=2).encode("utf-8")))
            os.replace(temp, PROFILE_PATH)
        except Exception as exc:
            self.show_output("PROFILE", f"Could not save profile: {exc}")

    def redeem_code(self, code_str):
        kind = self.firewall.verify_activation_code(code_str)
        if kind == "DEV":
            self.is_developer = self.is_lifetime = True
            self.profile.update(is_developer=True, is_lifetime=True)
        elif kind == "LIFETIME":
            self.is_lifetime = True
            self.profile["is_lifetime"] = True
        else:
            return False, "Invalid activation code."
        self.save_profile()
        return True, "Activation accepted."

    def trial_days_remaining(self):
        return 99999 if (self.is_lifetime or self.is_developer) else max(0, int(30 - ((time.time() - self.trial_start) / 86400)))

    def set_state(self, state):
        if self.state_cb:
            self.state_cb(state)

    def show_output(self, speaker, msg):
        if self.output_cb and msg:
            self.output_cb(speaker, str(msg))

    def speak(self, text):
        if text:
            self.show_output(self.assistant_name.upper(), text)

    def _track_file(self, filepath):
        self.last_created_file = filepath
        self.show_output("OUTPUT", f"Created: {filepath}")
        return filepath

    def _raw_ai_text(self, prompt):
        raw, _ = self.meta_brain.race_all_models(
            "Return only the requested file content. Do not add markdown fences.", prompt,
            preferred_model=self.preferred_model)
        if not raw:
            raise RuntimeError("No AI provider responded. Configure an API key or gateway.")
        return raw

    def modify_attached_file(self, instruction):
        if not self.attached_file_path or not os.path.exists(self.attached_file_path):
            return "No file attached."
        return self._track_file(inspect_and_modify_file(self.attached_file_path, instruction, self._raw_ai_text))

    def _handle_reflex(self, reflex):
        code = reflex.get("python_code", "")
        if code == "os._exit(0)":
            # Clean shutdown is handled by the UI; don't terminate the Python process abruptly.
            self.show_output("SYSTEM", "Use the window close button to exit.")
            return
        speech = reflex.get("speech", "")
        if code.startswith("open_url("):
            match = re.search(r"open_url\\(['\\\"](.*?)['\\\"]\\)", code)
            if match:
                open_url(match.group(1))
        elif code.startswith("run_system_command("):
            match = re.search(r"run_system_command\\(['\\\"](.*?)['\\\"]\\)", code)
            if match:
                run_system_command(match.group(1))
        elif "ImageGrab" in code:
            try:
                from PIL import ImageGrab
                path = os.path.join(CREATIONS_DIR, f"screenshot_{int(time.time())}.png")
                ImageGrab.grab().save(path)
                speech = f"Screenshot saved: {path}"
            except Exception as exc:
                speech = f"Screenshot failed: {exc}"
        if speech:
            self.speak(speech)

    def process_command(self, command):
        cmd = (command or "").strip()
        if not cmd:
            return
        self.show_output("YOU", cmd)
        self.chat_history.append({"role": "user", "content": cmd})
        if cmd.lower() in ("kushi24112010", "362025"):
            ok, message = self.redeem_code(cmd)
            self.speak(message)
            return
        reflex = self.meta_brain.instant_reflex(cmd)
        if reflex:
            self._handle_reflex(reflex)
            return
        if cmd.lower().startswith(("modify attached file ", "edit attached file ")):
            result = self.modify_attached_file(cmd.split(" ", 3)[-1])
            self.speak(result)
            return
        self.set_state("Thinking")
        try:
            raw, source = self.meta_brain.race_all_models(
                SYSTEM_PROMPT, cmd, preferred_model=self.preferred_model)
            if not raw:
                reply = ("I couldn't reach an AI provider. Check your internet connection and configure "
                         "an OpenRouter, OpenAI, Groq, Gemini, Cloudflare Worker, or local Ollama endpoint.")
            else:
                reply = raw.strip()
                if source:
                    self.show_output("MODEL", source)
            self.speak(reply)
            self.chat_history.append({"role": "assistant", "content": reply})
        finally:
            self.set_state("Ready")

    def background_voice_loop(self):
        if sr is None:
            self.show_output("VOICE", "Voice input is unavailable. Install SpeechRecognition and PyAudio.")
            return
        self.show_output("VOICE", "Voice capture is not started automatically; use a configured microphone workflow.")
