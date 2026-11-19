"""Desktop and media helper functions. Optional integrations fail with clear errors."""
import os, time, json, random, urllib.parse, webbrowser, subprocess, html
from pathlib import Path
import requests, certifi
try:
    import pyautogui
except Exception:
    pyautogui = None
try:
    import pyperclip
except Exception:
    pyperclip = None
from PIL import Image, ImageDraw


def _require_desktop():
    if pyautogui is None:
        raise RuntimeError("Desktop automation is unavailable in this session. Run on a desktop with a display.")


def human_type(text):
    _require_desktop()
    if not text:
        return
    if all(ord(c) < 128 for c in text):
        pyautogui.write(text, interval=random.uniform(.015, .04))
    else:
        if pyperclip is None:
            raise RuntimeError("Clipboard support is unavailable.")
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")


def human_click(x, y, clicks=1, button="left"):
    _require_desktop()
    pyautogui.moveTo(int(x), int(y), duration=random.uniform(.18, .35), tween=pyautogui.easeOutQuad)
    pyautogui.click(clicks=clicks, button=button)


def press_hotkey(*keys):
    _require_desktop()
    pyautogui.hotkey(*keys)


def open_url(url):
    if not str(url).startswith(("https://", "http://")):
        raise ValueError("Only HTTP(S) URLs are allowed.")
    webbrowser.open(url)


def generate_ai_image(worker_urls, prompt, save_dir, sign_fn=None):
    os.makedirs(save_dir, exist_ok=True)
    urls = [worker_urls] if isinstance(worker_urls, str) else [
        item["url"] if isinstance(item, dict) else item for item in (worker_urls or [])]
    urls = [u.rstrip("/") for u in urls if "workers.dev" in str(u)]
    random.shuffle(urls)
    if not urls:
        raise RuntimeError("No image gateway configured.")
    payload = {"prompt": prompt, "width": 1024, "height": 1024}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    errors = []
    for base in urls:
        try:
            headers = {"Content-Type": "application/json"}
            if sign_fn:
                headers.update(sign_fn("POST", "/imagine", body))
            response = requests.post(base + "/imagine", data=body, headers=headers,
                                     timeout=40, verify=certifi.where())
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "image" not in content_type and not response.content.startswith(b"\\x89PNG"):
                raise RuntimeError("Gateway response was not an image.")
            path = os.path.join(save_dir, f"aether_art_{int(time.time()*1000)}.png")
            with open(path, "wb") as f:
                f.write(response.content)
            return path
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("Image generation failed: " + "; ".join(errors))


def generate_sovereign_video(prompt, duration_seconds, save_dir, worker_urls=None, sign_fn=None):
    try:
        import numpy as np
        import imageio.v2 as imageio
    except ImportError as exc:
        raise RuntimeError("Install numpy and imageio[ffmpeg] to render MP4 video.") from exc
    os.makedirs(save_dir, exist_ok=True)
    duration = max(5, min(60, int(duration_seconds or 15)))
    out = os.path.join(save_dir, f"aether_video_{int(time.time())}.mp4")
    fps, width, height = 12, 854, 480
    scenes = [s.strip() for s in prompt.replace(";", ".").split(".") if s.strip()] or [prompt]
    per_scene = max(1, (duration * fps) // len(scenes))
    writer = imageio.get_writer(out, fps=fps, codec="libx264", quality=7)
    try:
        for frame in range(duration * fps):
            scene = min(len(scenes)-1, frame // per_scene)
            t = (frame % per_scene) / per_scene
            image = Image.new("RGB", (width, height), (13, 18, 32))
            draw = ImageDraw.Draw(image)
            x, y = int(width * (.3 + .4*t)), height // 2
            for radius in range(50, 250, 40):
                r = int(radius + 12*np.sin(frame*.12+radius))
                draw.ellipse((x-r, y-r, x+r, y+r), outline=(37, 99, 235), width=2)
            draw.rectangle((30, 25, width-30, 105), fill=(6, 10, 20), outline=(37, 99, 235))
            draw.text((48, 42), f"SCENE {scene+1}/{len(scenes)}", fill=(147, 197, 253))
            draw.text((48, 68), scenes[scene][:90], fill=(255, 255, 255))
            writer.append_data(np.asarray(image))
    finally:
        writer.close()
    return out


def inspect_and_modify_file(filepath, instruction, ask_ai_fn):
    if not os.path.isfile(filepath):
        raise FileNotFoundError(filepath)
    if os.path.getsize(filepath) > 2_000_000:
        raise ValueError("File is larger than the 2 MB editing limit.")
    text = Path(filepath).read_text(encoding="utf-8", errors="replace")
    updated = ask_ai_fn(f"Instruction: {instruction}\nFile: {os.path.basename(filepath)}\nContent:\\n{text}\\nReturn only the complete updated file.")
    updated = updated.strip()
    if updated.startswith("```"):
        updated = updated.split("\n", 1)[-1]
        if updated.endswith("```"):
            updated = updated[:-3].rstrip()
    if not updated:
        raise RuntimeError("AI returned an empty file; original was not changed.")
    base, ext = os.path.splitext(filepath)
    out = f"{base}_modified{ext}"
    Path(out).write_text(updated, encoding="utf-8")
    return out


def ue5_remote_execute(python_script):
    try:
        response = requests.put("http://127.0.0.1:30010/remote/object/call",
            json={"objectPath": "/Script/PythonScriptPlugin.Default__PythonScriptLibrary",
                  "functionName": "ExecutePythonCommand",
                  "parameters": {"PythonCommand": python_script}}, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def create_3d_game_project(title, genre, save_dir, worker_urls=None, sign_fn=None):
    os.makedirs(save_dir, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in title.lower()).strip("_") or "game"
    path = os.path.join(save_dir, safe + "_3d.html")
    safe_title, safe_genre = html.escape(title), html.escape(genre)
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title><style>body{{margin:0;background:#101827;color:#e5e7eb;font:16px system-ui;display:grid;place-items:center;min-height:100vh}}main{{padding:2rem;text-align:center}}</style>
<main><h1>{safe_title}</h1><p>Genre: {safe_genre}</p><p>Starter project generated by AETHER.</p></main></html>"""
    Path(path).write_text(page, encoding="utf-8")
    return path


def background_prepare_checkout(store, item_query):
    url = f"https://www.amazon.in/s?k={urllib.parse.quote_plus(item_query)}"
    webbrowser.open(url)
    return url


def run_system_command(cmd):
    # Restrict this helper to launching known local applications, not arbitrary shell text.
    allowed = {"chrome", "notepad", "calc", "mspaint", "cmd", "wt", "powershell",
               "explorer", "taskmgr", "rundll32.exe user32.dll,LockWorkStation",
               "start chrome", "start notepad", "start calc", "start mspaint",
               "start cmd", "start wt", "start powershell", "start explorer",
               "start taskmgr", "start ms-settings:"}
    if cmd not in allowed:
        raise ValueError("Command is not in the allowed application list.")
    if os.name == "nt":
        subprocess.Popen(cmd, shell=True)
    else:
        subprocess.Popen(cmd.split())
