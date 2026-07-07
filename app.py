"""
位置情報抽出ツール — メインアプリ (Streamlit)
ドキュメントから緯度・経度を抽出し KML/KMZ を生成します。
ローカルフォルダスキャン・ファイルアップロードの両モードに対応。
"""

import sys
import os
import tempfile
import shutil
from pathlib import Path

# Ensure imports resolve from project root regardless of CWD
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load .env for local runs; on Streamlit Cloud, secrets are used instead
from dotenv import load_dotenv
load_dotenv(dotenv_path=_ROOT / ".env")

import math
import streamlit as st
import pandas as pd
import folium
from branca.element import MacroElement
from jinja2 import Template
from streamlit_folium import st_folium

from core.extractor import scan_folder
# from core.parking_finder import cluster_points, find_parking_for_clusters  # [PARKING - DISABLED]
from exporters.kml_exporter import export_kml_bytes, export_kmz_bytes

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls"}


def _valid_coord(v) -> bool:
    """Return True only for a real finite number (not None, not NaN)."""
    try:
        return v is not None and not math.isnan(float(v))
    except (TypeError, ValueError):
        return False
SUPPORTED_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
]

# ─────────────────────────────────────────────
# Resolve API keys: Streamlit Secrets → .env → sidebar input
# ─────────────────────────────────────────────
def _get_secret(key: str) -> str:
    try:
        return st.secrets.get(key, "") or ""
    except Exception:
        return os.environ.get(key, "")


# ─────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="位置情報抽出ツール",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🗺️ ドキュメント位置情報抽出ツール")
st.caption("Word / Excel / PDF ファイルから緯度・経度を自動抽出し、Google マイマップ用の KML/KMZ を生成します。")

# ─────────────────────────────────────────────
# Sidebar — mode + settings
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 設定")

    # Render injects RENDER=true into every deployed service's environment.
    # A hosted instance has no access to the visitor's local filesystem, so
    # folder-scan mode (which reads a path on disk) only makes sense when
    # running locally via 起動.bat.
    IS_HOSTED = bool(os.environ.get("RENDER"))

    if IS_HOSTED:
        input_mode = "upload"
    else:
        input_mode = st.radio(
            "入力モード",
            options=["folder", "upload"],
            format_func=lambda x: "📁 ローカルフォルダ" if x == "folder" else "☁️ ファイルアップロード",
            help="ローカル実行時はフォルダ指定が便利です。オンライン共有時はアップロードをご利用ください。",
        )

    st.divider()

    # ── Input controls per mode ───────────────
    folder_path = None
    uploaded_files = None

    if input_mode == "folder":
        # Folder picker button — runs tkinter in a separate process to avoid
        # the Tcl_AsyncDelete thread crash that occurs when tkinter runs
        # inside Streamlit's background thread (tkinter needs a real main
        # thread). In the frozen desktop .exe build, sys.executable points at
        # the bundled exe itself rather than a generic python.exe, so instead
        # of "-c <script>" we re-launch the same exe with a special
        # --pick-folder flag that desktop_app.py handles by showing just the
        # dialog and exiting (see desktop_app.py::_pick_folder_and_exit).
        if st.button("📂 フォルダを選択", use_container_width=True):
            try:
                import subprocess

                if getattr(sys, "frozen", False):
                    cmd = [sys.executable, "--pick-folder"]
                    extra_kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW}
                else:
                    _script = (
                        "import tkinter as tk; from tkinter import filedialog; "
                        "root = tk.Tk(); root.withdraw(); "
                        "root.wm_attributes('-topmost', 1); "
                        "path = filedialog.askdirectory(title='フォルダを選択してください'); "
                        "root.destroy(); print(path)"
                    )
                    cmd = [sys.executable, "-c", _script]
                    extra_kwargs = {}

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=60, **extra_kwargs
                )
                picked = result.stdout.strip()
                if picked:
                    st.session_state["picked_folder"] = picked
            except Exception:
                st.warning("フォルダ選択ダイアログを開けませんでした。パスを直接入力してください。")

        folder_path = st.text_input(
            "📁 フォルダパス",
            value=st.session_state.get("picked_folder", ""),
            placeholder=r"例: C:\Users\yourname\Documents\現場資料",
            help="上のボタンでフォルダを選択するか、パスを直接入力してください。",
        )
        # Keep session state in sync if user types manually
        if folder_path != st.session_state.get("picked_folder", ""):
            st.session_state["picked_folder"] = folder_path
    else:
        uploaded_files = st.file_uploader(
            "📂 ファイルを選択またはドラッグ＆ドロップ",
            type=["pdf", "docx", "xlsx", "xls"],
            accept_multiple_files=True,
            help="複数ファイルを同時にアップロードできます（最大 30 件推奨）。",
        )

    # 地図画像解析セクションは現在非表示（将来実装予定）
    vision_backend = "none"

    st.divider()

    # Determine if scan button should be enabled
    can_scan = (
        (input_mode == "folder" and bool(folder_path and folder_path.strip()))
        or (input_mode == "upload" and bool(uploaded_files))
    )
    scan_btn = st.button(
        "🔍 ドキュメントをスキャン",
        type="primary",
        use_container_width=True,
        disabled=not can_scan,
    )

# ─────────────────────────────────────────────
# Scan action
# ─────────────────────────────────────────────
if scan_btn:
    tmp_dir = None  # only used in upload mode

    try:
        if input_mode == "folder":
            # ── Local folder mode ─────────────────
            scan_target = Path(folder_path.strip())
            if not scan_target.exists() or not scan_target.is_dir():
                st.error("❌ 指定されたフォルダが存在しません。パスを確認してください。")
                st.stop()
            files_in_folder = [
                f for f in scan_target.iterdir()
                if f.suffix.lower() in SUPPORTED_EXTENSIONS
            ]
            if not files_in_folder:
                st.warning("⚠️ フォルダ内に対応ファイル（PDF / Word / Excel）が見つかりませんでした。")
                st.stop()
            st.info(f"📂 スキャン対象: {len(files_in_folder)} 件のファイル")

        else:
            # ── Upload mode ───────────────────────
            # Save uploaded bytes to a temporary folder so existing readers can process them
            tmp_dir = tempfile.mkdtemp(prefix="geocode_upload_")
            for uf in uploaded_files:
                dest = Path(tmp_dir) / uf.name
                dest.write_bytes(uf.read())
            scan_target = Path(tmp_dir)
            st.info(f"📂 アップロードされたファイル: {len(uploaded_files)} 件")

        # ── Progress ──────────────────────────────
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        def _progress(current: int, total: int, filename: str) -> None:
            pct = current / total if total else 1.0
            progress_bar.progress(min(pct, 1.0))
            if filename:
                status_text.text(f"処理中 ({current + 1}/{total}): {filename}")
            else:
                status_text.text("✅ スキャン完了")

        results = scan_folder(
            str(scan_target),
            vision_backend=vision_backend,
            progress_callback=_progress,
        )
        st.session_state["results"] = results

    finally:
        # Clean up temp dir after scan (upload mode only)
        if tmp_dir and Path(tmp_dir).exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

# ─────────────────────────────────────────────
# Results display
# ─────────────────────────────────────────────
if "results" not in st.session_state:
    if input_mode == "folder":
        st.info("左のサイドバーでフォルダパスを入力し、「ドキュメントをスキャン」を押してください。")
    else:
        st.info("左のサイドバーでファイルをアップロードし、「ドキュメントをスキャン」を押してください。")
    st.stop()

results: list[dict] = st.session_state["results"]

success_list = [r for r in results if r["status"] == "success"]
manual_list  = [r for r in results if r["status"] in ("manual_review", "image_based_pdf")]
error_list   = [r for r in results if r["status"] == "error"]

# ── Summary metrics ───────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("📄 総ファイル数", len(results))
col2.metric("✅ 座標取得成功", len(success_list))
col3.metric("⚠️ 手動確認が必要", len(manual_list))
col4.metric("❌ エラー", len(error_list))

# ── Results table ─────────────────────────────
st.subheader("📋 スキャン結果")

if manual_list:
    st.warning(
        f"⚠️ {len(manual_list)} 件のファイルで座標が見つかりませんでした。"
        "下の表で緯度・経度を直接入力できます。"
    )

STATUS_LABELS = {
    "success":         "✅ 成功",
    "manual_review":   "⚠️ 手動確認",
    "image_based_pdf": "🖼️ 画像ベースPDF",
    "error":           "❌ エラー",
    "unsupported":     "⛔ 非対応",
    "processing":      "⏳ 処理中",
}

df_rows = []
for r in results:
    df_rows.append({
        "ファイル名":  r["filename"],
        "緯度":       r["lat"],
        "経度":       r["lon"],
        "取得方法":   r.get("method") or "",
        "ステータス": STATUS_LABELS.get(r["status"], r["status"]),
    })

df = pd.DataFrame(df_rows, index=range(1, len(df_rows) + 1))

edited_df = st.data_editor(
    df,
    column_config={
        "緯度": st.column_config.NumberColumn("緯度", format="%.6f", min_value=-90.0,  max_value=90.0),
        "経度": st.column_config.NumberColumn("経度", format="%.6f", min_value=-180.0, max_value=180.0),
    },
    disabled=["ファイル名", "取得方法", "ステータス"],
    use_container_width=True,
    num_rows="fixed",
    key="result_table",
)

# Apply manual edits back to results (index is 1-based, results list is 0-based)
for i, row in edited_df.iterrows():
    lat_val = row["緯度"]
    lon_val = row["経度"]
    if _valid_coord(lat_val) and _valid_coord(lon_val):
        results[i - 1]["lat"] = float(lat_val)
        results[i - 1]["lon"] = float(lon_val)
        if results[i - 1]["status"] in ("manual_review", "image_based_pdf"):
            results[i - 1]["status"] = "success"
            results[i - 1]["method"] = "手動入力"

# ── Map preview ───────────────────────────────
map_results = [r for r in results if r["status"] == "success" and _valid_coord(r["lat"]) and _valid_coord(r["lon"])]

if map_results:
    st.subheader("🗺️ 地図プレビュー")

    center_lat = sum(r["lat"] for r in map_results) / len(map_results)
    center_lon = sum(r["lon"] for r in map_results) / len(map_results)

    # CartoDB Voyager: cleaner than OSM, shows Japanese labels, roads colour-coded like Google Maps
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=15,
        tiles=None,
    )
    folium.TileLayer(
        tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        name="地図",
        max_zoom=19,
    ).add_to(m)

    # Auto-fit so all pins are visible without manual zoom
    if len(map_results) > 1:
        sw = [min(r["lat"] for r in map_results), min(r["lon"] for r in map_results)]
        ne = [max(r["lat"] for r in map_results), max(r["lon"] for r in map_results)]
        m.fit_bounds([sw, ne], padding=(40, 40))

    def _numbered_pin(n: int) -> str:
        label = str(n) if n <= 99 else "…"
        font_size = "10" if n >= 10 else "12"
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="38" viewBox="0 0 28 38">'
            '<path d="M14 0C6.268 0 0 6.268 0 14c0 9.333 14 24 14 24S28 23.333 28 14'
            'C28 6.268 21.732 0 14 0z" fill="#2563EB" stroke="white" stroke-width="1.5"/>'
            f'<text x="14" y="17" fill="white" font-size="{font_size}" font-family="Arial,sans-serif"'
            ' text-anchor="middle" dominant-baseline="middle" font-weight="bold">'
            f'{label}</text></svg>'
        )

    for idx, r in enumerate(map_results, start=1):
        popup_html = (
            f"<b>({idx}) {r['filename']}</b><br>"
            f"緯度: {r['lat']:.6f}<br>"
            f"経度: {r['lon']:.6f}<br>"
            f"取得方法: {r.get('method', '')}"
        )
        folium.Marker(
            location=[r["lat"], r["lon"]],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"({idx}) {Path(r['filename']).stem}",
            icon=folium.DivIcon(html=_numbered_pin(idx), icon_size=(28, 38), icon_anchor=(14, 38)),
        ).add_to(m)

    # Cooperative gesture control — mirrors hotel-finder's gestureHandling:'cooperative'
    # Ctrl+scroll = zoom; plain scroll = page scrolls + Japanese hint shown.
    # Drag = pan (no modifier needed, same as Google Maps desktop).
    # MacroElement renders its script AFTER Leaflet initialises the map,
    # so the map variable is available directly — no polling required.
    class _GestureControl(MacroElement):
        _template = Template(u"""
            {% macro script(this, kwargs) %}
            (function() {
                var lm = {{ this._parent.get_name() }};
                lm.scrollWheelZoom.disable();
                lm.doubleClickZoom.disable();
                lm.boxZoom.disable();
                lm.keyboard.disable();

                setTimeout(function() {
                    var zi = document.querySelector('.leaflet-control-zoom-in');
                    var zo = document.querySelector('.leaflet-control-zoom-out');
                    if (zi) zi.title = 'ズームイン';
                    if (zo) zo.title = 'ズームアウト';
                }, 300);

                var box = lm.getContainer();
                var tip = document.createElement('div');
                tip.style.cssText = 'position:absolute;top:50%;left:50%;'
                    + 'transform:translate(-50%,-50%);background:rgba(0,0,0,0.62);'
                    + 'color:#fff;padding:9px 18px;border-radius:6px;font-size:13px;'
                    + 'font-family:sans-serif;pointer-events:none;z-index:10000;'
                    + 'display:none;white-space:nowrap';
                tip.textContent = 'Ctrl キーを押しながらスクロールでズーム';
                box.appendChild(tip);

                var tmr;
                box.addEventListener('wheel', function(e) {
                    if (e.ctrlKey) {
                        e.preventDefault();
                        lm.setZoom(lm.getZoom() + (e.deltaY < 0 ? 1 : -1));
                    } else {
                        clearTimeout(tmr);
                        tip.style.display = 'block';
                        tmr = setTimeout(function() { tip.style.display = 'none'; }, 1800);
                    }
                }, { passive: false });
            })();
            {% endmacro %}
        """)
        def __init__(self):
            super().__init__()
            self._name = 'GestureControl'

    _GestureControl().add_to(m)

    st_folium(m, use_container_width=True, height=620)

    # ── Export ────────────────────────────────
    st.subheader("📥 エクスポート")
    st.caption(f"{len(map_results)} 件の位置情報を KML / KMZ としてダウンロードできます。")

    col_kml, col_kmz = st.columns(2)

    with col_kml:
        try:
            st.download_button(
                label="📁 KML ファイルをダウンロード",
                data=export_kml_bytes(results),
                file_name="locations.kml",
                mime="application/vnd.google-earth.kml+xml",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"KML 生成エラー: {e}")

    with col_kmz:
        try:
            st.download_button(
                label="📦 KMZ ファイルをダウンロード",
                data=export_kmz_bytes(results),
                file_name="locations.kmz",
                mime="application/vnd.google-earth.kmz",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"KMZ 生成エラー: {e}")

    # [PARKING - DISABLED] バックアップ: backups/parking_finder_v1.py
    # Street View Static API の有効化が必要なため一時停止中。
    # 再開する場合は parking_finder import のコメントを外してこのブロックを復元。

else:
    st.info("座標が取得できたファイルがありません。上の表で手動入力するか、別のファイルを試してください。")
