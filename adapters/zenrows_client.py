class ZenRowsClient:
    """
    Responsible for communicating with ZenRows.

    For now, this is a stub that returns sample HTML.
    Later, it will make real API requests.
    """

    def fetch_page(self, url: str) -> str:
        """
        Fetch HTML for a given URL.

        Parameters:
            url (str): The page to retrieve.

        Returns:
            str: HTML content.
        """

        print(f"[ZenRows] Fetching: {url}")

        return """
        <html>
            <body>
                <h1>Sample Page</h1>
                <p>This is placeholder HTML.</p>
            </body>
        </html>
        """