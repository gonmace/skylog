# -*- mode: python ; coding: utf-8 -*-


from PyInstaller.utils.hooks import collect_all

pil_datas, pil_binaries, pil_hiddenimports = collect_all('PIL')
req_datas, req_binaries, req_hiddenimports = collect_all('requests')

a = Analysis(
    ['agent.py'],
    pathex=[],
    binaries=[] + pil_binaries + req_binaries,
    datas=[('version.py', '.')] + pil_datas + req_datas,
    hiddenimports=[
        'websocket',
        'websocket._abnf',
        'websocket._core',
        'winreg',
        'certifi',
        'charset_normalizer',
        'idna',
    ] + pil_hiddenimports + req_hiddenimports,
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
    name='redline_agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
