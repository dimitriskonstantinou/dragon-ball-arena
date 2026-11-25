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

# After Step 42b, live (commit dda1fab, 2026-11-25)
The commit was deployed twice: 20:14 and 20:18 UTC (the second probably because the Blueprint added `CLIENT_IP_HEADER`; not confirmed).
- 20:16, first deploy: 9 wrong logins with changing fakes 401 x5, 429 x4; 25 more all 429. **Proves nothing about the fix:** all
  requests may have gone through one internal machine, which gives the same result. A limit test needs the logged address too.
- 20:18 on, second deploy: the logged address is the dev PC's own (compared with what Cloudflare reports, not printed); 1 + 4 wrong logins
  with changing fakes 401, then 429 x4, countdown 208 s = exactly the rest of the 300 s window.
- Faked `CF-Connecting-IP`: 403. Reload 10 of 10 (0.41-1.1 s), network drop 10 of 10, second tab / closed tab / leaving as intended, no
  browser errors (measured on the first deploy; independent of the header).
Not tested live: a second network, IPv6, mobile, the registration limit.
