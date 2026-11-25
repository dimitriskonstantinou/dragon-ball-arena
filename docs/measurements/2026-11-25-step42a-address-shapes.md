# Step 42a: how Render's address headers are built (live, commit 7fe57cf, 2026-11-25 19:36 UTC)

Logged by the temporary `address_probe.py` (letters = addresses within one line; no addresses were logged). Sent from the dev PC
(IPv4); `test` = the faked 203.0.113.x addresses. Not measured: IPv6, mobile data.

| Request | X-Forwarded-For | CF-Connecting-IP | True-Client-IP | Connection from |
|---|---|---|---|---|
| API, normal (7: normal1-4, http1, v4, underscore `CF_Connecting_IP` faked) | visitor, public (Cloudflare), private | visitor | visitor | loopback |
| API, X-Forwarded-For faked | test, visitor, public, private | visitor | visitor | loopback |
| API, two fakes (one header / two headers) | test, test, visitor, public, private | visitor | visitor | loopback |
| API, True-Client-IP or X-Real-IP faked | visitor, public, private | visitor | visitor (fake replaced) | loopback |
| API, all faked together | test, visitor, public, private | visitor | visitor | loopback |
| API, CF-Connecting-IP faked (also lower case) | refused with 403 before our server | | | |
| websocket, normal / True-Client-IP faked | visitor | visitor | visitor | loopback |
| websocket, X-Forwarded-For faked | test, visitor | visitor | visitor | loopback |
| polling, normal / True-Client-IP faked | visitor, public, private | visitor | visitor | loopback |
| polling, X-Forwarded-For faked | test, visitor, public, private | visitor | visitor | loopback |
| websocket / polling, CF-Connecting-IP faked | refused before our server | | | |

Also: X-Client-IP and Forwarded reach us as faked; X-Real-IP does not arrive. `ip=` in the logs (the last X-Forwarded-For
entry): an internal machine. Health checks come directly (no such headers).
