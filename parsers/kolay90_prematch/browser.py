"""Persistent ZenRows browser for Kolay90 prematch.

Reuses utils.zenrows_persistent.ZenRowsSession without modifying it.
The session is left open unless close() is called explicitly.
"""

from utils.zenrows_persistent import ZenRowsSession


class Kolay90PrematchBrowser:
    def __init__(self):
        self.session = ZenRowsSession()

    def page(self):
        return self.session.get_page()

    def close(self):
        self.session.close()
