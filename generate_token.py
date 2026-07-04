"""
STEP 1 — Run this once per trading day.

Kite Connect access tokens are invalidated daily (~6:00 AM IST),
so this script must be re-run each day before using test_all_apis.py.

What it does:
  1. Prints your Kite login URL — open it in a browser.
  2. You log in with your Zerodha client ID + password + 2FA.
  3. Kite redirects to your app's Redirect URL with ?request_token=XXXX
     in the address bar. Copy that request_token.
  4. Paste it here. The script exchanges it for an access_token and
     saves it to kite_session.json for the explorer script to reuse.

Prerequisite (one time):
  pip install kiteconnect
  Fill in API_KEY and API_SECRET below (from developers.kite.trade
  -> your app). Make sure the app's Redirect URL is set — even
  http://127.0.0.1 works; the page failing to load is fine, you only
  need the request_token from the URL bar.
"""

import json
import datetime
from kiteconnect import KiteConnect

# ---------------------------------------------------------------
API_KEY = "i983oh68z8684vb8"
API_SECRET = "9t1cgzeugbc9c61ros12rgt2vb0crvzh"
# ---------------------------------------------------------------

SESSION_FILE = "kite_session.json"


def main():
    kite = KiteConnect(api_key=API_KEY)

    print("\n1. Open this URL in your browser and log in:\n")
    print("   " + kite.login_url())
    print(
        "\n2. After login + 2FA, the browser redirects to your app's "
        "Redirect URL.\n   The address bar will contain "
        "...?request_token=XXXXXX&action=login&status=success"
    )

    request_token = input("\n3. Paste the request_token here: ").strip()

    data = kite.generate_session(request_token, api_secret=API_SECRET)

    session = {
        "api_key": API_KEY,
        "access_token": data["access_token"],
        "public_token": data.get("public_token", ""),
        "user_id": data.get("user_id", ""),
        "generated_at": datetime.datetime.now().isoformat(),
    }
    with open(SESSION_FILE, "w") as f:
        json.dump(session, f, indent=2)

    print("\nSuccess. Logged in as:", data.get("user_id"))
    print("access_token saved to", SESSION_FILE)
    print("Valid until ~6:00 AM IST tomorrow. Now run: python test_all_apis.py")


if __name__ == "__main__":
    main()