import json
import os

from parsers.onwin.browser import OnwinBrowser


ONWIN_PAGE = "https://onwin4505.com/sportsbook/live/main-line/soccer"
TARGET = "get_main_line.erisgaming"

OUTPUT_FILE = "output/onwin_main_line.json"


browser = OnwinBrowser()
page = browser.page()


found = False


def handle_response(response):
    global found

    if found:
        return

    if TARGET not in response.url:
        return

    print("\n" + "=" * 80)
    print("GET_MAIN_LINE RESPONSE FOUND")
    print("=" * 80)

    print("\nSTATUS:")
    print(response.status)

    print("\nURL:")
    print(response.url)

    # We only want successful responses.
    if response.status != 200:
        print("\nNot a 200 response. Ignoring.")
        print("=" * 80)
        return

    try:
        body = response.text()

        print("\nRESPONSE SIZE:")
        print(len(body), "bytes")

        if not body:
            print("\nResponse body is empty.")
            print("=" * 80)
            return

        print("\nFIRST 1000 CHARACTERS:")
        print(body[:1000])

        try:
            data = json.loads(body)

        except json.JSONDecodeError as e:
            print("\nResponse was not valid JSON.")
            print(e)
            print("=" * 80)
            return

        # Make sure output directory exists.
        os.makedirs(
            os.path.dirname(OUTPUT_FILE),
            exist_ok=True
        )

        with open(
            OUTPUT_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=2,
                ensure_ascii=False
            )

        found = True

        print("\n" + "=" * 80)
        print("SUCCESS!")
        print("=" * 80)

        print("\nSaved response to:")
        print(OUTPUT_FILE)

        print("\nResponse captured successfully.")
        print("We can now build the parser from this real snapshot.")

        print("=" * 80)

    except Exception as e:

        print("\nCould not read response body:")

        print(
            type(e).__name__,
            e
        )

        print("=" * 80)


# IMPORTANT:
# Attach the listener BEFORE navigating.
page.on("response", handle_response)


print("\nOpening Onwin...\n")


try:

    page.goto(
        ONWIN_PAGE,
        wait_until="domcontentloaded",
        timeout=30000
    )

except Exception as e:

    print(
        "\nNavigation finished with:",
        type(e).__name__
    )


print("\nCurrent page:")
print(page.url)


print("\nWaiting for get_main_line.erisgaming...")
print("The browser will remain open.")


# Don't use input() immediately.
# Give the page time to continue its JS/challenge/application loading.
for i in range(120):

    if found:
        break

    page.wait_for_timeout(1000)

    if i % 10 == 0:
        print(
            f"Still waiting... {i} seconds"
        )


if not found:

    print("\n" + "=" * 80)
    print("GET_MAIN_LINE RESPONSE WAS NOT CAPTURED")
    print("=" * 80)

    print(
        "\nThe browser remained open for 120 seconds,"
        " but no successful response body was captured."
    )

else:

    print("\nSnapshot capture complete.")


print("\nClosing browser session...")


browser.session.close()

print("Done.")