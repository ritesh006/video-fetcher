# Video Agent 🎥🤖

Universal video downloader agent built on `yt-dlp` featuring automated title search, intelligent multi-tier locker resolution (HubDrive, HubCloud, HubCDN, GreenMotors, HDStream4u), base64/URL parameter unpacking, and high-speed direct CDN stream extraction.

---

## 🌟 Key Features

- **🔍 Natural Title Search**: Simply pass movie or TV series titles (e.g. `"The Paradise 2026"`, `"Kantara"`, `"Deadpool"`). The agent searches the website index, sanitizes release tags, and selects the matching entry automatically.
- **🎯 Quality Filtering**: Target specific resolutions (`--quality 1080p`, `720p`, `4k`, `480p`).
- **⚡ Fast Locker Unpacking**: Introspects intermediate locker pages and prioritizes direct Cloudflare R2 / S3 / stream links over rate-limited hosts, completing resolution in under 3 seconds.
- **ℹ️ Metadata Inspection**: Inspect stream details, format options, and direct links without downloading using `--info`.
- **🗂️ Batch Processing**: Supply a text file via `--batch` containing multiple titles or URLs (one per line).
- **🎵 Audio Extraction**: Extract audio tracks directly to formats like MP3 using `--audio-only`.

---

## 📋 Prerequisites

- **Python 3.8+**
- **yt-dlp**: Required core downloader engine
- *(Recommended)* **ffmpeg**: Needed for merging audio/video streams at highest qualities and audio conversions
- *(Optional)* **deno**: Supported JS runtime for certain encrypted extractors

Install required dependencies:
```bash
pip install yt-dlp
```

---

## 🚀 Installation

### Option 1: Run directly with Python
Clone the repository and run directly:
```bash
python video_agent.py --quality 1080p "The Paradise 2026"
```

### Option 2: Install globally (CLI command)
To use the `video-agent` command anywhere across your system:
```bash
pip install -e .
```

---

## 💻 Usage & CLI Reference

### 1. Download by Title (Recommended)
You only need to supply the movie or show title:
```bash
# Search and download 1080p
python video_agent.py --quality 1080p "The Paradise 2026"

# Download with default best quality
python video_agent.py "The Paradise"

# Explicit flag
python video_agent.py --search "Inception" --quality 1080p
```

### 2. Inspect Details Without Downloading (`--info`)
Preview metadata, direct CDN links, title, and format availability:
```bash
python video_agent.py --quality 1080p --info "The Paradise 2026"
```

### 3. Interactive Selection (`--select`)
If a title search returns multiple matching releases or seasons, prompt to choose interactively:
```bash
python video_agent.py --select "Deadpool"
```

### 4. Direct URL Mode
If you already have a landing page or locker link:
```bash
python video_agent.py --quality 1080p "https://new10.hdhub4u.cl/the-paradise-2026-hindi-webrip-full-movie/"
```

### 5. Batch Download from File
Create a text file (e.g. `list.txt`) containing titles or URLs:
```text
The Paradise 2026
Inception
https://new10.hdhub4u.cl/kantara-chapter-1-2025-ds4k-hindi-webrip-full-movie/
```
Run batch download:
```bash
python video_agent.py --batch list.txt --quality 1080p -o ./downloads
```

### 6. Extract Audio Only
```bash
python video_agent.py --audio-only --audio-format mp3 "The Paradise"
```

---

## ⚙️ Command-Line Flags

| Flag | Description | Default |
| :--- | :--- | :--- |
| `targets` | Movie/series titles or page URLs to process | None |
| `--quality` | Desired video quality (`1080p`, `720p`, `4k`, `480p`) | Auto / Best |
| `--info` | Inspect and display metadata only (no download) | `False` |
| `--select` | Interactively choose from multiple search hits | `False` |
| `--search-index` | Pick a specific hit index (1-based) automatically | `1` |
| `--search-limit` | Maximum search hits to fetch from index | `5` |
| `--site` | Base website mirror URL | Auto-detected active mirror |
| `-o`, `--output-dir` | Directory where downloaded media is saved | `downloads` |
| `--jobs` | Maximum concurrent downloads | `4` |
| `--audio-only` | Extract audio track only | `False` |
| `--audio-format` | Target audio format (e.g. `mp3`, `m4a`, `wav`) | `mp3` |
| `--batch` | File path containing titles or URLs (one per line) | None |
| `-q`, `--quiet` | Suppress non-essential output | `False` |

---

## 🤖 Programmatic Integration

You can integrate `video_agent.py` into automated workflows or agent pipelines using standard subprocess calls:

```python
import subprocess

result = subprocess.run(
    ["python", "video_agent.py", "--quality", "1080p", "The Paradise 2026"],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("Download completed successfully!")
    print(result.stdout)
else:
    print("Download failed:", result.stderr)
```

---

## 📁 Repository Structure

```text
├── video_agent.py          # Core downloader and search resolution agent
├── pyproject.toml          # Project metadata and CLI entrypoint definition
├── README.md               # Comprehensive documentation and usage guide
├── .gitignore              # Ignored cache, virtual environments, and downloaded media
└── downloads/              # Default folder for downloaded media
```

---

## ⚠️ Disclaimer

This tool is intended strictly for educational, personal, and research purposes. Please respect copyright laws and the terms of service of any third-party websites or hosting platforms accessed.
