from browser.sessions.brightdata import BrightDataSession


def main():

    session = BrightDataSession()

    browser = session.connect()

    print("\nBrowser Version\n")
    print(browser.version)

    session.close()

    print("\nBrowser closed.")


if __name__ == "__main__":
    main()