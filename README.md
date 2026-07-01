# Geo Extractor — Document Location Extractor

Scans Word / Excel / PDF files, extracts latitude and longitude, and exports a KML or KMZ file ready to upload to Google My Maps.

The app runs in two modes:
- **Local folder scan** — point it at a folder on your PC (best when running locally)
- **File upload** — drag and drop files in the browser (works on Streamlit Cloud — no install for teammates)

---

## Option A: Run Locally (on your own PC)

### Prerequisites
- **Python 3.11 or later** — download from https://www.python.org/downloads/
  - During installation, check **"Add Python to PATH"**

### Setup (first time only)
Open PowerShell and run:
```powershell
cd C:\Users\Staff\Pich\GEOCODE\geo_extractor
pip install -r requirements.txt
```

### Start the app
```powershell
cd C:\Users\Staff\Pich\GEOCODE\geo_extractor
streamlit run app.py
```
The browser opens automatically at `http://localhost:8501`.
Keep PowerShell open while using the app.

### Share with teammates on the same office network
Instead of `streamlit run app.py`, run:
```powershell
streamlit run app.py --server.address 0.0.0.0
```
Then share your PC's local IP address (e.g. `http://192.168.1.10:8501`).
Teammates open that URL in any browser — no install needed on their side.
Documents must be in a folder path that your PC can access (e.g. a shared network drive).

---

## Option B: Deploy to Streamlit Cloud (online, free, no install for anyone)

In this mode, teammates open a URL from any device, anywhere.
They upload files directly in the browser instead of pointing to a local folder.

### Step 1 — Create a GitHub account (free)
Go to https://github.com and sign up if you don't have an account.

### Step 2 — Create a new GitHub repository
1. Click **New repository**
2. Name it (e.g. `geo-extractor`)
3. Set it to **Private** (your documents never go to GitHub — only the app code does)
4. Click **Create repository**

### Step 3 — Upload the app code to GitHub
In PowerShell:
```powershell
cd C:\Users\Staff\Pich\GEOCODE\geo_extractor
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/geo-extractor.git
git push -u origin main
```
Replace `YOUR_USERNAME` with your GitHub username.

### Step 4 — Deploy on Streamlit Cloud
1. Go to https://share.streamlit.io and sign in with GitHub
2. Click **New app**
3. Select your repository (`geo-extractor`), branch (`main`), and file (`app.py`)
4. Click **Deploy**

Streamlit Cloud builds the app automatically (takes 2–3 minutes).
You get a shareable URL like `https://your-app.streamlit.app`.

### Step 5 — Add API keys (if using Claude Vision or Google Vision)
In the Streamlit Cloud dashboard:
1. Open your app → click **Settings** → **Secrets**
2. Paste the following and fill in your keys:
```toml
ANTHROPIC_API_KEY = "sk-ant-xxxxxxxx"
```
The app reads these automatically. Teammates never see the keys.

---

## How to Use the App

### Step 1 — Choose input mode (sidebar)
| Mode | When to use |
|------|------------|
| 📁 ローカルフォルダ | Running on your PC — type a folder path |
| ☁️ ファイルアップロード | Running on Streamlit Cloud — drag and drop files |

### Step 2 — (Optional) Set up map image analysis
If documents only contain a map screenshot with no text coordinates, the app can use AI to read the map.

- **Claude Vision (recommended):** Enter your Anthropic API key
- **Google Vision:** Enter your Google Maps API key
- **Skip:** Documents without text coordinates will be flagged for manual entry

### Step 3 — Scan
Click **「ドキュメントをスキャン」**. A progress bar shows each file being processed.

### Step 4 — Review results
| Column | Meaning |
|--------|---------|
| ファイル名 | Document filename |
| 緯度 / 経度 | Extracted latitude / longitude |
| 取得方法 | How it was found (text, map image, or manual) |
| ステータス | ✅ Success / ⚠️ Needs review / ❌ Error |

Rows marked ⚠️ can be edited — click the 緯度/経度 cell and type coordinates directly.

### Step 5 — Preview on map
All found locations appear as pins on an interactive map.

### Step 6 — Export
Download **KML** or **KMZ**, then upload to [Google My Maps](https://www.google.com/maps/d/).

---

## Supported Coordinate Formats

| Format | Example |
|--------|---------|
| Japanese DMS | 北緯35度41分22秒 東経139度41分30秒 |
| English DMS | 35°41'22"N 139°41'30"E |
| Decimal (Japanese label) | 緯度: 35.6895 / 経度: 139.6917 |
| Decimal (English label) | Latitude: 35.6895 / Longitude: 139.6917 |
| Decimal with direction | 35.6895°N, 139.6917°E |
| Plain decimal pair | 35.689500, 139.691700 |
| Full-width digits | ３５．６８９５、１３９．６９１７ |

Text is scanned on **pages 1 and 2** only.

---

## Current Limitations

| # | Limitation |
|---|------------|
| 1 | Only scans **pages 1–2** of each document |
| 2 | **Excel images** cannot be extracted — only cell text works |
| 3 | Word page boundaries are approximate (first 100 paragraphs) |
| 4 | Map image analysis **requires an API key** and has a per-image cost |
| 5 | Low-resolution or unlabeled map images may give poor results |
| 6 | Only **one coordinate pair per document** (first one found wins) |
| 7 | Old `.xls` format may fail — convert to `.xlsx` first |
| 8 | **Scanned / image-only PDFs** (no OCR) cannot be read by text extraction |
| 9 | No Japan-range filter — coordinates in foreign documents could match |

---

## Storing API Keys Permanently (local use)

Copy `.env.example` to `.env` in the same folder and fill in your key:
```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
```
The app loads this automatically on startup so you don't have to type it each time.

---

## Project Structure

```
geo_extractor/
├── app.py                       ← Streamlit UI (run this)
├── requirements.txt
├── .env.example                 ← Copy to .env and add API keys (local use)
├── .streamlit/
│   ├── config.toml              ← Streamlit settings (upload size, theme)
│   └── secrets.toml.example    ← Template for Streamlit Cloud secrets
├── core/
│   ├── coord_parser.py          ← Regex coordinate extraction (JP + EN)
│   ├── image_analyzer.py        ← Claude / Google Vision wrapper
│   └── extractor.py             ← Main pipeline per document
├── readers/
│   ├── pdf_reader.py
│   ├── word_reader.py
│   └── excel_reader.py
└── exporters/
    └── kml_exporter.py
```
