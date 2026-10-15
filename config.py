# Orbit Exchange WebSocket endpoint.
#
# NOTE: this hardcodes a specific SockJS server-id/session-id pair
# captured from one past browser session. SockJS sessions are
# single-use, so parsers/orbit/client.py no longer imports this
# constant -- it generates a fresh server-id/session-id pair on the
# same base path for every connect() call instead. Left here
# unmodified/unused rather than deleted.
ORBIT_WS_URL = (
    "wss://www.orbitxch.com/"
    "customer/ws/multiple-market-prices/"
    "610/"
    "2a9f9a94-6d15-4c30-a9e2-5da941ea737b/"
    "websocket"
)

# Cookies copied from your browser
ORBIT_COOKIES = (
    "BIAB_LANGUAGE=en; "
    "COLLAPSE_SIDEBAR=false; "
    "BIAB_TZ=-180; "
    "COLLAPSE-LEFT_PANEL_COLLAPSE_GROUP-SPORT_COLLAPSE=true; "
    "BIAB_AN=ead97c02-9101-47f3-99cf-e1deb0b5c955; "
    "CSRF-TOKEN=a95b617c-c16d-4297-885d-476f7061fccb; "
    "AWSALB=HdmCBwOUUaHiryv2FwtUtmeoZyCcUU//29ixkbam8bxfDJcxspQJUidEchidJtC6nYAyeXIGSCfPUHG9HHD3MGA8Xo+1Y2wDcjPu0MtrkXOkCrSzT1ZGZQdFiQ0F; "
    "AWSALBCORS=HdmCBwOUUaHiryv2FwtUtmeoZyCcUU//29ixkbam8bxfDJcxspQJUidEchidJtC6nYAyeXIGSCfPUHG9HHD3MGA8Xo+1Y2wDcjPu0MtrkXOkCrSzT1ZGZQdFiQ0F"
)

# REST endpoint
ORBIT_REST_URL = (
    "https://www.orbitxch.com/customer/api/inplay/highlights?page=0&size=30"
)

# CSRF token
ORBIT_CSRF_TOKEN = "a95b617c-c16d-4297-885d-476f7061fccb"