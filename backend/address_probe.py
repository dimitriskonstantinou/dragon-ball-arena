"""
TEMPORARY (Step 42a, SEC-9; removed in 42b): logs how the host's address headers are BUILT, so the
rate limits can use the one that holds the real visitor. Only on the test site (ENV=staging).

Never logs an address: each one becomes a letter (the same address = the same letter, within one line
only) plus a category, e.g.  x-forwarded-for=[A:test,B:public,C:private] cf-connecting-ip=[B:public]
"""
import ipaddress
import threading

HEADERS = ('X-Forwarded-For', 'X-Real-IP', 'CF-Connecting-IP', 'CF-Connecting-IPv6', 'True-Client-IP', 'X-Client-IP',
           'Forwarded', 'CF-Pseudo-IPv4', 'X-Forwarded-Proto')
MAX_ENTRIES = 8          # of one header; the rest is only counted
MAX_LINES = 300          # per server start
TEST_NET = ipaddress.ip_network('203.0.113.0/24')   # reserved for documentation: the faked addresses of our own checks

_lines = 0
_lock = threading.Lock()


def category(address):
    if address in TEST_NET:
        return 'test'
    if address.is_loopback:
        return 'loopback'
    if address.is_private:
        return 'private'
    return 'public' if address.is_global else 'other'


def shape(environ, remote):
    """One line describing the address headers of a request (WSGI environ), without any address in it."""
    letters, parts = {}, []

    def describe(text):
        try:
            address = ipaddress.ip_address(text.strip())
        except ValueError:
            return 'empty' if not text.strip() else 'not-an-address'
        letter = letters.setdefault(address, chr(ord('A') + min(len(letters), 25)))
        return f"{letter}:{category(address)}/v{address.version}"

    for header in HEADERS:
        value = environ.get('HTTP_' + header.upper().replace('-', '_'))
        if value is None:
            continue
        entries = value.split(',')
        if header in ('X-Forwarded-Proto', 'Forwarded'):
            parts.append(f"{header.lower()}=present({len(entries)})")
            continue
        described = [describe(e) for e in entries[:MAX_ENTRIES]]
        if len(entries) > MAX_ENTRIES:
            described.append(f"+{len(entries) - MAX_ENTRIES} more")
        parts.append(f"{header.lower()}=[{','.join(described)}]")
    parts.append(f"connection-from=[{describe(remote or '')}]")
    return ' '.join(parts)


def log_shape(log, kind, environ):
    global _lines
    with _lock:
        if _lines >= MAX_LINES:
            return
        _lines += 1
    # ProxyFix replaces REMOTE_ADDR and keeps the original here.
    original = environ.get('werkzeug.proxy_fix.orig') or {}
    log.info("Address shape: kind=%s %s", kind, shape(environ, original.get('REMOTE_ADDR') or environ.get('REMOTE_ADDR')))
