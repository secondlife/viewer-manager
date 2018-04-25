# PyInstaller hook for the dnspython snapshot embedded in eventlet

from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules('eventlet.support.dns')
