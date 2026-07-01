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

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

from core.extractor import scan_folder
from exporters.kml_exporter import export_kml_bytes, export_kmz_bytes

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls"}
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
        folder_path = st.text_input(
            "📁 フォルダパス",
            placeholder=r"例: C:\Users\yourname\Documents\現場資料",
            help="スキャン対象ファイル（Word / Excel / PDF）が入ったフォルダのパスを入力してください。",
        )
    else:
        uploaded_files = st.file_uploader(
            "📂 ファイルを選択またはドラッグ＆ドロップ",
            type=["pdf", "docx", "xlsx", "xls"],
            accept_multiple_files=True,
            help="複数ファイルを同時にアップロードできます（最大 30 件推奨）。",
        )

    st.divider()
    st.subheader("🔑 地図画像解析（オプション）")
    st.caption("テキストに座標が見つからない場合、ドキュメント内の地図画像を AI で解析します。")

    vision_backend = st.selectbox(
        "バックエンド",
        options=["none", "claude", "google"],
        format_func=lambda x: {
            "none": "使用しない",
            "claude": "Claude Vision（推奨）",
            "google": "Google Vision + Geocoding",
        }[x],
    )

    if vision_backend == "claude":
        key_val = st.text_input(
            "Anthropic API キー",
            type="password",
            value=_get_secret("ANTHROPIC_API_KEY"),
            help="sk-ant-... で始まるキーを入力してください。",
        )
        if key_val:
            os.environ["ANTHROPIC_API_KEY"] = key_val

    elif vision_backend == "google":
        key_val = st.text_input(
            "Google Maps API キー",
            type="password",
            value=_get_secret("GOOGLE_MAPS_API_KEY"),
        )
        if key_val:
            os.environ["GOOGLE_MAPS_API_KEY"] = key_val

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
manual_list  = [r for r in results if r["status"] == "manual_review"]
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
    "success":       "✅ 成功",
    "manual_review": "⚠️ 手動確認",
    "error":         "❌ エラー",
    "unsupported":   "⛔ 非対応",
    "processing":    "⏳ 処理中",
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

df = pd.DataFrame(df_rows)

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

# Apply manual edits back to results
for i, row in edited_df.iterrows():
    lat_val = row["緯度"]
    lon_val = row["経度"]
    if lat_val is not None and lon_val is not None:
        results[i]["lat"] = float(lat_val)
        results[i]["lon"] = float(lon_val)
        if results[i]["status"] == "manual_review":
            results[i]["status"] = "success"
            results[i]["method"] = "手動入力"

# ── Map preview ───────────────────────────────
map_results = [r for r in results if r["status"] == "success" and r["lat"] and r["lon"]]

if map_results:
    st.subheader("🗺️ 地図プレビュー")

    center_lat = sum(r["lat"] for r in map_results) / len(map_results)
    center_lon = sum(r["lon"] for r in map_results) / len(map_results)

    m = folium.Map(location=[center_lat, center_lon], zoom_start=10)

    for r in map_results:
        popup_html = (
            f"<b>{r['filename']}</b><br>"
            f"緯度: {r['lat']:.6f}<br>"
            f"経度: {r['lon']:.6f}<br>"
            f"取得方法: {r.get('method', '')}"
        )
        folium.Marker(
            location=[r["lat"], r["lon"]],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=Path(r["filename"]).stem,
        ).add_to(m)

    st_folium(m, use_container_width=True, height=500)

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

else:
    st.info("座標が取得できたファイルがありません。上の表で手動入力するか、別のファイルを試してください。")
