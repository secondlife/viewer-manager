# PyInstaller hook for dynamic import of dnspython

from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules('dns')
