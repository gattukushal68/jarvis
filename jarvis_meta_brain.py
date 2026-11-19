"""Provider router and local similarity memory."""
from __future__ import annotations
import os, re, sys, json, time, hashlib, concurrent.futures
import numpy as np
import requests
import certifi
from security_firewall import dpapi_protect, dpapi_unprotect

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
NEURAL_WEIGHTS_PATH = os.path.join(BASE_DIR, "jarvis_brain_weights.npz")
DISTILLED_MEMORY_PATH = os.path.join(BASE_DIR, "jarvis_distilled_memory.dat")

FEDERATION_ENDPOINTS = [
    {"id": "cf_acc1", "name": "Cloudflare Worker 1", "url": "https://jarvis-neural-gateway.gattuchowdappa121.workers.dev/think", "type": "cf_worker"},
    {"id": "cf_acc2_main", "name": "Cloudflare Worker 2", "url": "https://jarvis-neural-gateway.gattukushal68.workers.dev/think", "type": "cf_worker"},
    {"id": "cf_acc2_beta", "name": "Cloudflare Worker beta", "url": "https://jarvis-neural-gateway-beta.gattukushal68.workers.dev/think", "type": "cf_worker"},
    {"id": "openrouter_free", "name": "OpenRouter", "url": "https://openrouter.ai/api/v1/chat/completions", "type": "openai_compat", "model": "openrouter/free"},
    {"id": "ollama_local", "name": "Ollama local", "url": "http://127.0.0.1:11434/api/chat", "type": "ollama"},
]


class SovereignMetaBrain:
    def __init__(self, profile, sign_fn=None):
        self.profile, self.sign_fn = profile, sign_fn
        self.dim = 256
        self.distilled_examples = self._load_distilled_memory()
        self.W1, self.W2 = self._load_or_init_weights()

    def _featurize(self, text):
        vec = np.zeros(self.dim, dtype=np.float32)
        clean = re.sub(r"[^a-z0-9\s]", " ", str(text).lower()).strip()
        for token in clean.split():
            vec[int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dim] += 1
        for i in range(max(0, len(clean) - 2)):
            tri = clean[i:i+3]
            vec[int(hashlib.sha1(tri.encode()).hexdigest(), 16) % self.dim] += .5
        norm = np.linalg.norm(vec)
        return vec / norm if norm else vec

    def _load_distilled_memory(self):
        try:
            with open(DISTILLED_MEMORY_PATH, "rb") as f:
                data = json.loads(dpapi_unprotect(f.read()).decode())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_distilled_memory(self):
        try:
            with open(DISTILLED_MEMORY_PATH, "wb") as f:
                f.write(dpapi_protect(json.dumps(self.distilled_examples[-300:]).encode()))
        except OSError:
            pass

    def _load_or_init_weights(self):
        try:
            with np.load(NEURAL_WEIGHTS_PATH) as data:
                w1, w2 = data["W1"], data["W2"]
                if w1.shape == (self.dim, 64) and w2.shape == (64, self.dim):
                    return w1, w2
        except Exception:
            pass
        rng = np.random.default_rng(42)
        return (rng.normal(0, .08, (self.dim, 64)).astype(np.float32),
                rng.normal(0, .08, (64, self.dim)).astype(np.float32))

    def learn_from_experience(self, prompt, speech, python_code=""):
        if not prompt or not speech:
            return
        self.distilled_examples.append({"prompt": prompt.strip().lower(), "speech": speech,
                                        "python_code": "", "ts": time.time()})
        self._save_distilled_memory()

    def recall_distilled(self, prompt):
        q = self._featurize(prompt)
        best, score = None, 0.0
        for item in reversed(self.distilled_examples):
            if not isinstance(item, dict) or not item.get("prompt"):
                continue
            candidate = float(np.dot(q, self._featurize(item["prompt"])))
            if candidate > score:
                best, score = item, candidate
        if best and score >= .91:
            return {"speech": best.get("speech", ""), "python_code": "", "new_skill_trigger": ""}
        return None

    def instant_reflex(self, prompt):
        low = re.sub(r"[\\\\/`'\\\"]+", "", prompt.strip().lower()).strip()
        if low in {"close jarvis", "exit jarvis", "quit jarvis", "shutdown jarvis", "close app", "exit", "quit", "terminate"}:
            return {"speech": "Use the window close button to exit.", "python_code": ""}
        if low in {"screenshot", "take screenshot", "capture screen"}:
            return {"speech": "Taking a screenshot.", "python_code": "SCREENSHOT"}
        if low in {"lock pc", "lock computer", "lock screen"}:
            return {"speech": "Locking your workstation.", "python_code": "LOCK"}
        if low in {"what time is it", "current time", "time", "date", "what is the date"}:
            return {"speech": f"It is {time.strftime('%I:%M %p on %A, %B %d, %Y')}.", "python_code": ""}
        match = re.match(r"^(?:open|launch|start)\s+([a-z0-9 ._-]+)$", low)
        if match:
            app = match.group(1).strip()
            urls = {"youtube": "https://www.youtube.com", "google": "https://www.google.com",
                    "github": "https://github.com", "whatsapp": "https://web.whatsapp.com",
                    "gmail": "https://mail.google.com"}
            commands = {"chrome": ["chrome"], "google chrome": ["chrome"], "notepad": ["notepad"],
                        "calculator": ["calc"], "calc": ["calc"], "paint": ["mspaint"],
                        "cmd": ["cmd"], "terminal": ["wt"], "powershell": ["powershell"],
                        "explorer": ["explorer"], "file explorer": ["explorer"], "task manager": ["taskmgr"]}
            if app in urls:
                return {"speech": f"Opening {app}.", "python_code": "URL:" + urls[app]}
            if app in commands:
                return {"speech": f"Opening {app}.", "python_code": "APP:" + commands[app][0]}
        return None

    def _query_single_node(self, node, system_prompt, user_prompt, img_b64=None):
        kind, url = node["type"], node["url"]
        if kind == "cf_worker":
            payload = {"system_prompt": system_prompt, "user_prompt": user_prompt}
            if img_b64:
                payload["image_b64"] = img_b64
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
            headers = {"Content-Type": "application/json"}
            if self.sign_fn:
                headers.update(self.sign_fn("POST", "/think", body))
            response = requests.post(url, data=body, headers=headers, timeout=12, verify=certifi.where())
            response.raise_for_status()
            result = response.json().get("reply", "")
        elif kind == "openai_compat":
            key = self.profile.get(node.get("key_field", "openrouter_api_key"), "")
            if not key and node["id"] == "openrouter_free":
                # The free router may accept unauthenticated requests depending on provider policy.
                key = ""
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            payload = {"model": node["model"], "messages": [
                {"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                "temperature": .4}
            response = requests.post(url, json=payload, headers=headers, timeout=15, verify=certifi.where())
            response.raise_for_status()
            result = response.json()["choices"][0]["message"]["content"]
        elif kind == "ollama":
            payload = {"model": self.profile.get("ollama_model", "qwen3:8b"),
                       "messages": [{"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt}], "stream": False}
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            result = response.json().get("message", {}).get("content", "")
        elif kind == "gemini_direct":
            key = self.profile.get("gemini_api_key", "")
            response = requests.post(f"{url}?key={key}",
                json={"contents": [{"parts": [{"text": system_prompt + "\n" + user_prompt}]}]},
                timeout=15, verify=certifi.where())
            response.raise_for_status()
            result = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            raise RuntimeError("Unknown provider type")
        result = str(result or "").strip()
        if not result:
            raise RuntimeError("Empty provider response")
        return result, node["name"]

    def race_all_models(self, system_prompt, user_prompt, img_b64=None, preferred_model="AUTO"):
        nodes = list(FEDERATION_ENDPOINTS)
        if self.profile.get("gemini_api_key"):
            nodes.append({"id": "gemini", "name": "Google Gemini", "url":
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                "type": "gemini_direct"})
        if self.profile.get("openai_api_key"):
            nodes.append({"id": "openai", "name": "OpenAI", "url":
                "https://api.openai.com/v1/chat/completions", "type": "openai_compat",
                "model": "gpt-4o-mini", "key_field": "openai_api_key"})
        if self.profile.get("groq_api_key"):
            nodes.append({"id": "groq", "name": "Groq", "url":
                "https://api.groq.com/openai/v1/chat/completions", "type": "openai_compat",
                "model": "llama-3.3-70b-versatile", "key_field": "groq_api_key"})
        if preferred_model and preferred_model != "AUTO":
            selected = [n for n in nodes if preferred_model.lower() in n["id"].lower()
                        or preferred_model.lower() in n["name"].lower()]
            if selected:
                nodes = selected
        if not nodes:
            return "", ""
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(nodes)))
        futures = [pool.submit(self._query_single_node, n, system_prompt, user_prompt, img_b64) for n in nodes]
        try:
            for future in concurrent.futures.as_completed(futures, timeout=16):
                try:
                    answer = future.result()
                    if answer and answer[0]:
                        return answer
                except Exception:
                    continue
        except concurrent.futures.TimeoutError:
            pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return "", ""
