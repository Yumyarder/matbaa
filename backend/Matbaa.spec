# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('app\\frontend_dist', 'frontend_dist'),
         # read beside their modules (app/fonts.py, app/deasciify.py)
         ('app\\fonts\\literata\\Literata-*.ttf', 'app\\fonts\\literata'),
         ('app\\fonts\\literata\\OFL.txt', 'app\\fonts\\literata'),
         ('app\\fonts\\charis\\*', 'app\\fonts\\charis'),
         ('app\\data', 'app\\data')]
binaries = []
hiddenimports = ['app.main', 'app.models', 'app.session_store', 'app.parsers.pdf_parser', 'app.builders.epub_builder', 'app.builders.css_template', 'app.utils.text_cleaning']
tmp_ret = collect_all('fitz')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pymupdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ebooklib')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['run_server.py'],
    pathex=[],
    binaries=binaries,
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
    name='Matbaa',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
