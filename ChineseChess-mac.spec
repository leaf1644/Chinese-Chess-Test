# -*- mode: python ; coding: utf-8 -*-
# macOS 打包用（請在 Mac 上執行）：
#   python3 -m PyInstaller --noconfirm --clean ChineseChess-mac.spec
#
# 注意：不要使用 Windows 的 pikafish.exe；請放 macOS 可執行檔「pikafish」。

a = Analysis(
    ['chess.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('pikafish', '.'),
        ('pikafish.nnue', '.'),
        ('assets', 'assets'),
        ('endgames.json', '.'),
        ('language.json', '.'),
    ],
    hiddenimports=['xiangqi', 'xiangqi.i18n', 'xiangqi.engine', 'xiangqi.paths'],
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
    [],
    exclude_binaries=True,
    name='ChineseChess',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ChineseChess',
)
app = BUNDLE(
    coll,
    name='ChineseChess.app',
    icon=None,
    bundle_identifier='com.chinesechess.app',
    info_plist={
        'NSHighResolutionCapable': True,
        'CFBundleDisplayName': '中國象棋',
        'CFBundleName': 'ChineseChess',
        'CFBundleShortVersionString': '3.2',
    },
)
