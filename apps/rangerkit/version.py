"""Single source of the kit's version string.

Apps report their own version from their own ``core/version.py``; this one
names the vendored kit so a unit in the field can be asked which rangerkit it
is running.
"""

__version__ = "0.1.0"
KIT_NAME = "rangerkit"
