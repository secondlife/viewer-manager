# https://pythonhosted.org/PyInstaller/hooks.html

try:
    from eventlet.hubs import builtin_hub_names
except ImportError:
    # I'm not confident the import above will work in the PyInstaller context
    # in which we need to use this.
    builtin_hub_names = ('epolls', 'kqueue', 'poll', 'selects')

hiddenimports = [
    ("eventlet.hubs." + name) for name in builtin_hub_names
]
