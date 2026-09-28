"""UnTangleMate."""
__version__ = "2.6.10.42"

# The product name, in ONE place. It has changed twice (Untanglemator 竊・# UntangleMate 竊・UnTangleMate) and each time it was spelled out in the
# splash, the window title, the tray and the About box separately 窶・so
# they drifted. Import these rather than typing the name again.
APP_NAME = "UnTangleMate"
APP_ABBREV = "UTM"
APP_NAME_FULL = f"{APP_NAME} ({APP_ABBREV})"

# Who publishes it. Same reasoning as the name above: these were typed
# out separately in the About box, the status-bar link and the support
# menu. The licence agreement needs all three as well, and a company
# name that differs between the agreement and the About box is worse
# than a typo.
COMPANY_NAME = "Synthetic Code Lab"
COMPANY_WEBSITE = "https://syntheticcodelab.com"
SUPPORT_EMAIL = "support@syntheticcodelab.com"

# QSettings scope. Qt builds the storage path out of these two names —
# on Windows, HKCU\Software\<org>\<app> — so changing them moves EVERY
# stored setting: window geometry, recent files, the accepted licence
# agreement, the sync options, panel state. They were "Synthetic Mind
# Map", the app's old name; `settings.migrate_legacy_scope()` copies the
# old scope into the new one once, so the rename does not read to the
# user as "the app forgot everything".
#
# NOT used for the licence, which lives in the app-data folder resolved
# by core.user_dirs.app_data_dir() and must keep doing so — moving an
# activated licence would deactivate an install that was working.
QSETTINGS_ORG = "UnTangleMate"
QSETTINGS_APP = "UnTangleMate"
LEGACY_QSETTINGS_ORG = "Synthetic Mind Map"
LEGACY_QSETTINGS_APP = "Synthetic Mind Map"
