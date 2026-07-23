from flask import Flask, render_template_string, request, jsonify, send_file, after_this_request
from werkzeug.utils import secure_filename
import yt_dlp
import threading
import os
import re

app = Flask(__name__)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

progress = {"status": "idle", "percent": 0, "title": "", "filename": ""}
download_lock = threading.Lock()

def sanitize_filename(filename):
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)

def sizeof_fmt(num, suffix="B"):
    for unit in ["", "K", "M", "G", "T"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}P{suffix}"

HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ZIGFT Audio Downloader</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body {background-color: #0a0f24; color: white; font-family: 'Poppins', sans-serif; text-align: center; padding: 40px;}
.card {background: #111936; border-radius: 20px; box-shadow: 0 0 15px rgba(0,0,0,0.5); padding: 25px; max-width: 600px; margin: auto;}
.thumbnail {width: 280px; border-radius: 15px; margin: 10px 0; box-shadow: 0 0 10px rgba(255,255,255,0.3);}
.title {font-weight: bold; font-size: 18px; color: #1e90ff;}
.progress {background-color: #1c2541; border-radius: 10px; height: 22px; margin-top: 15px;}
.progress-bar {transition: width 0.3s linear;}
</style>
</head>
<body>
<h1 class="text-info mb-3">🎵 ZIGFT Audio Downloader</h1>
<div class="card">
<input type="text" id="url" class="form-control" placeholder="Tempel link YouTube di sini...">
<div id="preview" style="display:none;">
  <img id="thumbnail" class="thumbnail" src="">
  <div class="title" id="title"></div>
</div>
<button id="downloadBtn" class="btn btn-success w-100 mt-3">🎧 Unduh Audio MP3</button>
<div id="loading" style="display:none;">
  <div class="progress">
    <div id="progressBar" class="progress-bar progress-bar-striped progress-bar-animated bg-success" style="width:0%"></div>
  </div>
  <div id="progressText" class="mt-2">Menunggu...</div>
</div>
</div>

<script>
async function fetchPreview() {
  const url = document.getElementById("url").value.trim();
  if (!url) return;
  const res = await fetch("/info", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({url})
  });
  const data = await res.json();
  if (data.thumbnail) {
    document.getElementById("thumbnail").src = data.thumbnail;
    document.getElementById("title").innerText = data.title;
    document.getElementById("preview").style.display = "block";
  }
}

document.getElementById("url").addEventListener("input", () => {
  clearTimeout(window.previewTimeout);
  window.previewTimeout = setTimeout(fetchPreview, 800);
});

document.getElementById("downloadBtn").addEventListener("click", async () => {
  const url = document.getElementById("url").value.trim();
  if (!url) return alert("Masukkan URL dulu bro!");

  document.getElementById("loading").style.display = "block";
  document.getElementById("progressText").innerText = "Menyiapkan unduhan...";

  fetch("/download", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({url})
  });

  const interval = setInterval(async () => {
    const res = await fetch("/progress");
    const data = await res.json();

    if (data.status === "done") {
      clearInterval(interval);
      document.getElementById("progressBar").style.width = "100%";
      document.getElementById("progressText").innerText = "✅ Selesai! Mengunduh...";
      window.location.href = "/file/" + encodeURIComponent(data.filename);
    } else if (data.status === "downloading") {
      document.getElementById("progressBar").style.width = data.percent + "%";
      document.getElementById("progressText").innerText = data.percent + "% • " + data.title;
    } else if (data.status === "processing") {
      document.getElementById("progressText").innerText = "🔄 Memproses audio...";
    } else if (data.status === "error") {
      clearInterval(interval);
      document.getElementById("progressText").innerText = data.title;
      document.getElementById("progressBar").classList.remove("bg-success");
      document.getElementById("progressBar").classList.add("bg-danger");
    }
  }, 1000);
});
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/info", methods=["POST"])
def info():
    url = request.json.get("url")
    try:
        ydl_opts = {"quiet": True, "nocheckcertificate": True, "cachedir": False}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return jsonify({
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail")
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/download", methods=["POST"])
def download():
    url = request.json["url"]
    progress.update({
        "status": "starting",
        "percent": 0,
        "title": "Menyiapkan unduhan baru...",
        "filename": ""
    })
    threading.Thread(target=download_audio, args=(url,)).start()
    return jsonify({"status": "started"})

@app.route("/progress")
def get_progress():
    return jsonify(progress)

@app.route("/file/<path:filename>")
def file(filename):
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(file_path):
        return "File tidak ditemukan", 404

    # ✅ Hapus file otomatis setelah dikirim ke user
    @after_this_request
    def remove_file(response):
        try:
            os.remove(file_path)
            print(f"[INFO] File {filename} berhasil dihapus setelah diunduh.")
        except Exception as e:
            print(f"[WARNING] Gagal menghapus file {filename}: {e}")
        return response

    return send_file(file_path, as_attachment=True)

def download_audio(url):
    global progress
    with download_lock:
        # bersihin file lama biar gak bentrok
        for f in os.listdir(DOWNLOAD_DIR):
            try:
                os.remove(os.path.join(DOWNLOAD_DIR, f))
            except:
                pass

        progress.update({
            "status": "downloading",
            "percent": 0,
            "title": "Mulai...",
            "filename": ""
        })

        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                downloaded = d.get("downloaded_bytes", 0)
                percent = downloaded / total * 100
                progress.update({
                    "status": "downloading",
                    "percent": round(percent, 1),
                    "title": f"{sizeof_fmt(downloaded)} / {sizeof_fmt(total)}"
                })
            elif d["status"] == "finished":
                progress.update({"status": "processing", "percent": 100, "title": "🔄 Memproses audio..."})

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{DOWNLOAD_DIR}/%(title)s.%(ext)s",
            "progress_hooks": [hook],
            "noplaylist": True,
            "nocheckcertificate": True,
            "cachedir": False,
            "ignoreerrors": True,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": 5,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = sanitize_filename(info.get("title", "audio"))
                mp3_path = os.path.join(DOWNLOAD_DIR, f"{title}.mp3")
                safe_name = secure_filename(f"{title}.mp3")

                # pastikan file ditemukan
                if not os.path.exists(mp3_path):
                    for f in os.listdir(DOWNLOAD_DIR):
                        if f.endswith(".mp3"):
                            mp3_path = os.path.join(DOWNLOAD_DIR, f)
                            safe_name = f
                            break

                os.rename(mp3_path, os.path.join(DOWNLOAD_DIR, safe_name))

                progress.update({
                    "filename": safe_name,
                    "status": "done",
                    "title": f"✅ Selesai mengunduh: {title}"
                })

        except Exception as e:
            progress.update({"status": "error", "title": f"❌ Gagal: {str(e)}"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7070, debug=True)
