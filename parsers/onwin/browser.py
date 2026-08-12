from utils.zenrows_persistent import ZenRowsSession


class OnwinBrowser:

    def __init__(self):
        self.session = ZenRowsSession()

    def page(self):
        return self.session.get_page()