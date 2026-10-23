# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

"""The HTTP contract of the llms routes, in one place.

WHY THIS FILE EXISTS
    QA-16 (FINDINGS S6/S12 G.7) was a hardcoded ``Cache-Control``: the three
    generation modes all answered ``public, max-age=3600``, so "Cached (Daily)"
    was a label and "Real-time" was a lie.  QA-25 (S3/S12 G.6) was the other
    half -- ``/llms.md`` sent no ``Cache-Control`` at all, the per-record item
    routes sent neither ``Cache-Control`` nor ``X-Robots-Tag``, and no route sent
    ``ETag`` or ``Last-Modified``, so a crawler polling once an hour paid for the
    whole document every time.  Both live in the *header*, not the body, which is
    why no model-level test ever caught them.

    Putting the answer in one module-level function means a route handler cannot
    forget a header: it asks for a response and gets the contract with it.

WHY IT IS DUPLICATED
    Each of the three addons is sold standalone and must be installable alone
    (mission rule 4: no cross-module dependency), so the companions cannot import
    this from ``llms_txt_agent``.  It is therefore copied byte-identically into
    each module exactly like ``html_to_md.py``, and the same sync test covers it.
    A future "make it one shared module" change would break standalone installs.

NO ``odoo`` IMPORT
    Like ``html_to_md.py``, this file stays loadable with plain ``importlib`` and
    no database, which is what makes the header contract unit-testable.  The
    request object is passed in and duck-typed (``make_response``,
    ``httprequest.headers``), never imported.
"""

import hashlib
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime

# QA-16: the one table that maps a Generation Mode to what it promises a cache,
# and the one place that decides how long a cached document stays fresh.  Both
# halves matter together: the label in Settings, the ``Cache-Control`` a crawler
# is told, and the interval the cron works on used to be three separate opinions
# (FINDINGS D-F, S6, S12 G.7 -- "Cached (Daily)" answering ``max-age=3600`` while
# a 6-hour cron rebuilt it).
#
# ``realtime`` regenerates on every request, so it must not be stored anywhere --
# ``no-cache`` says "revalidate before you reuse this", not "never send a
# validator", which is why the ETag is still offered in that mode.
CACHE_POLICY_BY_MODE = {
    'realtime': {'max_age': None, 'cache_control': 'no-cache, must-revalidate'},
    'hourly': {'max_age': 3600, 'cache_control': 'public, max-age=3600'},
    'daily': {'max_age': 86400, 'cache_control': 'public, max-age=86400'},
}
DEFAULT_POLICY = {'max_age': None, 'cache_control': 'no-cache, must-revalidate'}


def _policy(mode):
    """The policy for one generation mode; unknown modes get the safe one.

    An unrecognised mode (a future selection value, or a field write from an
    integration) must never inherit a stale ``max-age=3600`` default.
    """
    return CACHE_POLICY_BY_MODE.get(mode, DEFAULT_POLICY)


def cache_control_for(mode):
    """The ``Cache-Control`` value promised by one generation mode (QA-16)."""
    return _policy(mode)['cache_control']


def max_age_seconds(mode):
    """How long a cached document stays fresh for one mode, or ``None``.

    ``None`` means "this mode is not cached at all", which is what the cron uses to
    leave real-time websites alone (FINDINGS D-F: it used to write cache fields for
    them) and to decide when a cached website is actually due a rebuild (QA-16).
    """
    return _policy(mode)['max_age']


def etag_for(content):
    """A strong validator for the exact bytes being served (QA-25).

    A digest of the body rather than a timestamp: two requests for the same
    document must produce the same header even when the cache timestamp moved,
    and a changed document must produce a different one even inside the same
    second.  SHA-1 here is an identity check, not a security boundary.
    """
    if content is None:
        content = ''
    if isinstance(content, str):
        content = content.encode('utf-8')
    return '"%s"' % hashlib.sha1(content).hexdigest()


def _as_utc(value):
    """Normalise an Odoo naive-UTC datetime (or its text form) to aware UTC."""
    if value is None or value == False:  # noqa: E712 - record fields give False
        return None
    if isinstance(value, str):
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
            try:
                value = datetime.strptime(value.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def http_date(value):
    """RFC 7231 IMF-fixdate for ``Last-Modified``, or ``None``."""
    utc = _as_utc(value)
    return format_datetime(utc, usegmt=True) if utc else None


def parse_http_date(value):
    """Parse a client ``If-Modified-Since`` / ``If-Unmodified-Since`` value.

    Anything unparseable returns ``None`` so the caller serves the document: a
    malformed validator is a client bug, not a reason for a 500.
    """
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _etag_matches(header_value, etag):
    """Weak-comparison match of one ETag against an ``If-None-Match`` value."""
    if not header_value:
        return False
    candidates = [part.strip() for part in header_value.split(',') if part.strip()]
    if '*' in candidates:
        return True
    for candidate in candidates:
        if candidate.startswith('W/'):
            candidate = candidate[2:].strip()
        if candidate == etag:
            return True
        # tolerate a client that echoes the digest without its quotes
        if candidate.strip('"') == etag.strip('"'):
            return True
    return False


def is_not_modified(if_none_match, if_modified_since, etag, last_modified):
    """Should this request be answered with a 304? (QA-25)

    RFC 9110 order is respected: when ``If-None-Match`` is present it alone
    decides, so a client that sends both and whose ETag is stale gets the full
    body even if its date would have matched.
    """
    if if_none_match:
        return _etag_matches(if_none_match, etag)
    if if_modified_since and last_modified:
        since = parse_http_date(if_modified_since)
        modified = _as_utc(last_modified)
        if since and modified:
            # HTTP dates have one-second resolution; compare at that resolution.
            return modified.replace(microsecond=0) <= since
    return False


def response_headers(content, content_type, cache_control, lang=None,
                     last_modified=None, robots='all'):
    """Every header one llms document is allowed to send (QA-16, QA-25, QA-24).

    Kept as a list of tuples, the shape ``make_response`` expects, so a caller can
    still add a route-specific header without touching this contract.
    """
    headers = [
        ('Content-Type', content_type),
        ('Cache-Control', cache_control),
        ('X-Robots-Tag', robots),
        ('ETag', etag_for(content)),
    ]
    http_last_modified = http_date(last_modified)
    if http_last_modified:
        headers.append(('Last-Modified', http_last_modified))
    if lang:
        # QA-24: the document is per-language, so a shared cache may not reuse it
        # across languages.  ``Content-Language`` describes what we sent.  ``Vary``
        # has to name *both* headers because in Odoo 19 the language of a frontend
        # response does not come from Accept-Language at all -- http_routing picks
        # the URL prefix, then the ``frontend_lang`` cookie, then the context
        # (``odoo19/addons/http_routing/models/ir_http.py:403-407``), and nothing in
        # core reads Accept-Language.  Varying on it alone would still let a CDN
        # answer a French crawler with the English body it stored for the crawler
        # before it, which is the exact outage QA-24 was written to prevent.
        headers.append(('Content-Language', lang))
        headers.append(('Vary', 'Accept-Language, Cookie'))
    return headers


def not_modified_headers(etag, cache_control, last_modified=None):
    """The headers of a 304: validators and the cache directive, nothing else.

    A 304 must not repeat entity headers (RFC 9110 §15.4.5), so no Content-Type,
    no Content-Length and no Content-Language here.
    """
    headers = [
        ('ETag', etag),
        ('Cache-Control', cache_control),
    ]
    http_last_modified = http_date(last_modified)
    if http_last_modified:
        headers.append(('Last-Modified', http_last_modified))
    headers.append(('Vary', 'Accept-Language, Cookie'))
    return headers


def respond(request, content, content_type, cache_control, lang=None,
            last_modified=None, robots='all'):
    """Build the full response for one llms document, conditional GET included.

    ``request`` is Odoo's thread-local request, passed in rather than imported to
    keep this file importable without a database.
    """
    etag = etag_for(content)
    client_headers = request.httprequest.headers
    if is_not_modified(client_headers.get('If-None-Match'),
                       client_headers.get('If-Modified-Since'),
                       etag, last_modified):
        return request.make_response(
            '', status=304,
            headers=not_modified_headers(etag, cache_control, last_modified))
    return request.make_response(
        content,
        headers=response_headers(content, content_type, cache_control, lang,
                                 last_modified, robots))
