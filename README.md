# AETHER / JARVIS — repaired project

## What is included
- `main.py`: simplified, responsive desktop chat UI (small-window/mobile-width friendly).
- `jarvis_core.py`: assistant engine, profile storage, safe local command dispatch, optional account bridge.
- `jarvis_meta_brain.py`: parallel AI provider routing and local similarity memory.
- `omniverse_tools.py`: desktop automation, image/video helpers, file editing, starter HTML project.
- `security_firewall.py`: Windows DPAPI storage, PBKDF2 password hashing, voiceprint helpers, audit log.

## Install
Python 3.10+ is recommended. On Windows, open PowerShell in this folder:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

If PyAudio installation fails, install a compatible wheel for your Python version or omit it; text chat still works.

## Configure AI
The app needs internet access and at least one working provider. Add provider keys to the local
profile file only if you understand the security implications, or set environment variables and
extend the profile loader. Supported profile keys: `openrouter_api_key`, `openai_api_key`,
`groq_api_key`, `gemini_api_key`, and `ollama_model`. The Cloudflare worker endpoints are
configured in `jarvis_meta_brain.py`; they must be online and accept the documented `/think` payload.
Ollama requires Ollama running locally with the selected model pulled.

The bundled project cannot guarantee third-party gateway uptime, API quotas, model availability,
microphone drivers, Windows permissions, or external service schemas. No software can honestly
promise 100% operation across all machines. Core local UI and basic commands work without AI.

## Basic commands
- `time` / `what time is it`
- `open chrome`, `open notepad`, `open calculator`
- `open google`, `open youtube`, `open gmail`
- `screenshot` (Pillow screen capture support required)
- Attach a text/code file, then enter `modify attached file <instruction>` (requires AI provider)

## Important limitations and safety
- The UI is a desktop Tkinter application with a responsive narrow-window layout; it is not a
  native Android/iOS app.
- Remote command polling/execution is disabled to prevent a cloud account from executing
  arbitrary commands on your computer.
- Couple pairing is local-only until a real authenticated backend is implemented.
- The 3D project helper creates a starter HTML page, not a full 3D game engine project.
- The video helper renders a simple animated title-card MP4, not AI-generated cinematic footage.
- DPAPI encryption is available on Windows. On non-Windows systems profile/vault bytes are not
  protected by Windows DPAPI.
- Do not publish API keys, activation codes, profile files, voiceprints, or vault files.

## Run checks
```powershell
python -m compileall -q .
python -m unittest discover -s tests -v
```
