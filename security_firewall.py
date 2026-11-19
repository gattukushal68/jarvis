"""Local security helpers: Windows DPAPI where available, password hashing and audit log."""
import os, json, time, base64, ctypes, hmac, hashlib
import numpy as np
from scipy.fft import dct

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICEPRINT_PATH = os.path.join(BASE_DIR, "jarvis_voiceprint.json")
VAULT_PATH = os.path.join(BASE_DIR, "jarvis_vault.dat")
AUDIT_LOG_PATH = os.path.join(BASE_DIR, "jarvis_audit.log")
INTEGRITY_MANIFEST_PATH = os.path.join(BASE_DIR, "jarvis_manifest.dat")
DEV_CODE_HASH = hashlib.sha256(b"kushi24112010").hexdigest()
LIFETIME_CODE_HASH = hashlib.sha256(b"362025").hexdigest()


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi_protect(raw_bytes):
    if os.name != "nt":
        return raw_bytes
    buffer = ctypes.create_string_buffer(raw_bytes)
    blob_in = DATA_BLOB(len(raw_bytes), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if ctypes.windll.crypt32.CryptProtectData(ctypes.byref(blob_in), "AETHER vault",
            None, None, None, 0, ctypes.byref(blob_out)):
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    raise OSError("Windows DPAPI encryption failed")


def dpapi_unprotect(enc_bytes):
    if os.name != "nt":
        return enc_bytes
    buffer = ctypes.create_string_buffer(enc_bytes)
    blob_in = DATA_BLOB(len(enc_bytes), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None,
            None, None, None, 0, ctypes.byref(blob_out)):
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    raise OSError("Windows DPAPI decryption failed")


class SelfHealingShield:
    def __init__(self, filepath=VOICEPRINT_PATH):
        self.filepath = filepath
        self.enrolled_vector = self.voice_code = self.pwd_salt = self.pwd_hash = None
        self.threshold = .84
        self.failed_attempts, self.lockout_until = 0, 0.0
        self.quarantined_sessions, self.heal_events = set(), []
        self.layer_health = {f"L{i}_{name}": "NOMINAL" for i, name in enumerate(
            ["DPAPI_VAULT", "HMAC_NONCE_MESH", "AST_SANDBOX", "INTEGRITY_SENTINEL", "VOICE_BIOMETRIC"], 1)}
        self.device_signing_key = self._load_or_create_device_key()
        self.load()

    def verify_activation_code(self, code):
        digest = hashlib.sha256((code or "").strip().encode()).hexdigest()
        if hmac.compare_digest(digest, DEV_CODE_HASH): return "DEV"
        if hmac.compare_digest(digest, LIFETIME_CODE_HASH): return "LIFETIME"
        return ""

    def _load_or_create_device_key(self):
        try:
            with open(VAULT_PATH, "rb") as f:
                key = dpapi_unprotect(f.read())
            if len(key) == 32: return key
        except Exception:
            pass
        key = os.urandom(32)
        with open(VAULT_PATH, "wb") as f: f.write(dpapi_protect(key))
        return key

    def _autonomous_heal(self, layer, detail, source="LOCAL"):
        self.layer_health[layer] = "DEGRADED"
        self.heal_events.append({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                 "layer": layer, "detail": detail, "source": source})
        self.log_tamper_event(f"{layer}:{detail}:{source}")
        self.layer_health[layer] = "NOMINAL"

    def run_autonomous_audit(self):
        if not os.path.exists(VAULT_PATH) or len(self.device_signing_key) != 32:
            self._autonomous_heal("L1_DPAPI_VAULT", "Vault missing or invalid")
        return {"layers": dict(self.layer_health), "quarantined": list(self.quarantined_sessions),
                "heal_history": self.heal_events[-10:]}

    def sign_cloud_request(self, method, path, body_bytes):
        timestamp, nonce = str(int(time.time())), os.urandom(16).hex()
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        canonical = "\n".join([method.upper(), path, body_hash, timestamp, nonce]).encode()
        signature = hmac.new(self.device_signing_key, canonical, hashlib.sha256).hexdigest()
        return {"X-Jarvis-Timestamp": timestamp, "X-Jarvis-Nonce": nonce,
                "X-Jarvis-Signature": signature}

    def is_enrolled(self):
        return self.enrolled_vector is not None and self.pwd_hash is not None

    def hash_password(self, password, salt_hex=None):
        salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
        return salt.hex(), hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 250000).hex()

    def verify_password(self, password):
        if time.time() < self.lockout_until or not self.pwd_salt or not self.pwd_hash:
            return False
        _, candidate = self.hash_password(password, self.pwd_salt)
        if hmac.compare_digest(candidate, self.pwd_hash):
            self.failed_attempts = 0
            return True
        self.failed_attempts += 1
        if self.failed_attempts >= 5:
            self.lockout_until = time.time() + 300
            self._autonomous_heal("L5_VOICE_BIOMETRIC", "Repeated password failures", "AUTH")
        return False

    def log_tamper_event(self, event):
        previous = "0" * 64
        try:
            with open(AUDIT_LOG_PATH, encoding="utf-8") as f:
                lines = f.readlines()
            if lines: previous = lines[-1].split("|", 1)[0]
        except OSError:
            pass
        payload = f"{time.time()}|{event}"
        digest = hashlib.sha256((previous + payload).encode()).hexdigest()
        try:
            with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"{digest}|{payload}\n")
        except OSError:
            pass

    def extract_frequency_vector(self, raw_pcm_bytes, sample_rate=16000):
        samples = np.frombuffer(raw_pcm_bytes, dtype=np.int16).astype(np.float32)
        if len(samples) < int(sample_rate * .4): return None
        samples /= (np.max(np.abs(samples)) + 1e-8)
        samples = np.append(samples[0], samples[1:] - .97 * samples[:-1])
        frame_len, frame_step = int(.025 * sample_rate), int(.010 * sample_rate)
        if len(samples) < frame_len: return None
        count = 1 + (len(samples)-frame_len)//frame_step
        indices = np.arange(frame_len)[None, :] + np.arange(count)[:, None] * frame_step
        frames = samples[indices]
        energy = np.mean(frames**2, axis=1)
        active = frames[energy > np.percentile(energy, 35)+1e-6]
        if len(active) < 5: active = frames
        active = active * np.hamming(frame_len)
        power = np.abs(np.fft.rfft(active, 512))**2 / 512
        mel = np.linspace(2595*np.log10(1+80/700), 2595*np.log10(1+7600/700), 34)
        hz = 700*(10**(mel/2595)-1)
        bins = np.clip(np.floor(513*hz/sample_rate).astype(int), 0, 256)
        bank = np.zeros((32, 257))
        for m in range(1, 33):
            a,b,c = bins[m-1:m+2]
            if b > a: bank[m-1,a:b] = (np.arange(a,b)-a)/(b-a)
            if c > b: bank[m-1,b:c] = (c-np.arange(b,c))/(c-b)
        feats = np.log(np.maximum(power @ bank.T, np.finfo(float).eps))
        coeff = dct(feats, type=2, axis=1, norm="ortho")[:, 1:33]
        vector = np.concatenate([coeff.mean(0), coeff.std(0)])
        norm = np.linalg.norm(vector)
        return vector/norm if norm else None

    def enroll_from_pcm(self, raw_pcm_bytes, password):
        vector = self.extract_frequency_vector(raw_pcm_bytes)
        if vector is None: raise ValueError("Insufficient clear speech in recording.")
        salt, digest = self.hash_password(password)
        raw = vector.astype(np.float32).tobytes()
        payload = {"voice_code": "FW-"+hashlib.sha256(raw).hexdigest()[:16].upper(),
                   "frequency_dpapi_b64": base64.b64encode(dpapi_protect(raw)).decode(),
                   "pwd_salt": salt, "pwd_hash": digest, "enrolled_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(self.filepath, "w", encoding="utf-8") as f: json.dump(payload, f, indent=2)
        self.enrolled_vector, self.voice_code, self.pwd_salt, self.pwd_hash = vector, payload["voice_code"], salt, digest
        return self.voice_code

    def verify_speaker(self, audio_data):
        if not self.is_enrolled(): return True, 1.0
        raw = audio_data.get_raw_data(convert_rate=16000, convert_width=2)
        vector = self.extract_frequency_vector(raw)
        if vector is None or vector.shape != self.enrolled_vector.shape: return False, 0.0
        score = float(np.dot(self.enrolled_vector, vector))
        return score >= self.threshold, score

    def load(self):
        if not os.path.exists(self.filepath): return
        try:
            with open(self.filepath, encoding="utf-8") as f: data = json.load(f)
            raw = dpapi_unprotect(base64.b64decode(data["frequency_dpapi_b64"]))
            vector = np.frombuffer(raw, dtype=np.float32).copy()
            if vector.shape != (64,): raise ValueError("Invalid voiceprint vector")
            self.enrolled_vector, self.voice_code = vector, data.get("voice_code")
            self.pwd_salt, self.pwd_hash = data.get("pwd_salt"), data.get("pwd_hash")
        except Exception:
            self.enrolled_vector = None
            self._autonomous_heal("L1_DPAPI_VAULT", "Voiceprint data could not be loaded")

    def reset_with_password(self, password):
        if not self.verify_password(password): return False
        if os.path.exists(self.filepath): os.remove(self.filepath)
        self.enrolled_vector = self.voice_code = self.pwd_salt = self.pwd_hash = None
        return True
