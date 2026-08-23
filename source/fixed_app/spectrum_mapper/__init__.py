"""ChromaMatter application identity.

The public version is deliberately pinned.  It must not be changed merely
because fixes are added; only an explicit user request may advance it.
"""

APP_NAME = "ChromaMatter"
APP_TAGLINE = "AI Model Print Studio"
APP_DISPLAY_NAME = f"{APP_NAME} — {APP_TAGLINE}"
__version__ = "0.8beta"
VERSION_PINNED_UNTIL_USER_REQUEST = True
RELEASE_REVISION = "r32.1"
EDITION_LABEL = f"{APP_TAGLINE} {RELEASE_REVISION}"

__all__ = [
    "APP_DISPLAY_NAME",
    "APP_NAME",
    "APP_TAGLINE",
    "EDITION_LABEL",
    "RELEASE_REVISION",
    "VERSION_PINNED_UNTIL_USER_REQUEST",
    "__version__",
]
