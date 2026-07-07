# PyInstaller spec for the standalone desktop build.
# Build with:  pyinstaller geo_extractor.spec
# (must run inside a venv that has requirements.txt installed)
#
# console=True is intentional here, not leftover debug config: with no
# pywebview window, this console is the only visible sign the app is running
# and the way the user quits it (close the window to stop the server).

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = [
    ("app.py", "."),
    (".streamlit/config.toml", ".streamlit"),
]
datas += collect_data_files("streamlit")
datas += collect_data_files("streamlit_folium")
datas += collect_data_files("folium")
datas += collect_data_files("branca")
datas += copy_metadata("streamlit")

hiddenimports = []
hiddenimports += collect_submodules("streamlit")
hiddenimports += collect_submodules("streamlit_folium")

# app.py's own dependencies. These must be bundled (so PyInstaller's static
# analysis can find them) WITHOUT being actually imported anywhere in
# desktop_app.py — see the comment at the top of desktop_app.py for why.
hiddenimports += [
    "core.extractor",
    "core.coord_parser",
    "core.plane_rectangular",
    "core.image_analyzer",
    "readers.pdf_reader",
    "readers.word_reader",
    "readers.excel_reader",
    "exporters.kml_exporter",
    "pandas",
    "folium",
    "branca",
    "jinja2",
    "dotenv",
]

a = Analysis(
    ["desktop_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GeoExtractor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
