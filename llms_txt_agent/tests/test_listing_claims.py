# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

"""W8 / QA-31 -- every endpoint and UI label the store listing names is real.

The base listing's "real output" screenshot was a hand-made browser mock whose
``## Full Context Export`` section advertised ``/exports/context.xml``,
``/exports/dataset.json`` and ``/exports/archive.txt``.  None of those routes
exist in any of the three addons, so a buyer comparing the picture with their
own ``/llms.txt`` sees endpoints their install can never serve.

The image itself has been replaced with a capture of a live response (see
``qa_evidence/out/``), and this test is the guard that keeps the *text* honest:
route-shaped tokens in the listing HTML, the manifest description and the
README must each be a rule this module's controller actually registers, and
every route the module registers must appear in the listing.
"""

import ast
import html
import os
import re

import odoo.http as odoo_http
from odoo.tests.common import TransactionCase, tagged

MODULE = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ``https://mywebsite.com/exports/context.xml`` (the shape QA-31 found in the
# mock) is an invented endpoint too, so only the scheme+host is dropped and the
# path stays for inspection.  Bare external links such as https://llmstxt.org
# leave nothing behind.
ABSOLUTE_HOST = re.compile(r'https?://[^/\s>"\']+')
# A route-shaped token: /llms.txt, /llms/page/<id>.md, /exports/context.xml.
# The placeholder part refuses a leading slash, so ``</code>`` right after a
# route in the listing HTML is not mistaken for one.
ROUTE_TOKEN = re.compile(r'/(?:llms|exports)[A-Za-z0-9_.:/-]*(?:<[^>/]{1,40}>[A-Za-z0-9_.:/-]*)*')
PATH_PARAM = re.compile(r'<[^>/]{1,40}>')
TRAILING = '`*_.\'")],;: '

# The screens and buttons the listing promises an admin can find.  Each must
# appear verbatim in this module's own views or field definitions, so a rename
# in code turns the listing test red instead of leaving the store page stale.
LISTING_UI_LABELS = (
    'AI Search SEO (llms.txt & Markdown)',
    'Site Title',
    'Site Summary / Tagline',
    'LLM Guidance / Prompt',
    'Generation & Cache Mode',
    'Include Published Website Pages',
    'Rebuild Cache Now',
    'Cache Last Rebuilt',
    'AI Search Optimization (GEO / llms.txt)',
    'Exclude from llms.txt',
    'Custom AI Description (Markdown)',
)

# Claims the listing makes about what the generated document contains.
LISTING_DOCUMENT_MARKERS = (
    '## LLM Guidance',
    'Full Markdown Export',
)

# A companion's screenshot shows its own section heading, so the companion guard
# has to see that heading in a real document.  In a database installed without
# demo content the section is legitimately empty, so each module seeds one
# published record of the model its listing promises to index.  Keyed by module
# name so the three copies of this file stay byte-identical apart from the two
# tuples the generator swaps.
LISTING_MARKER_FIXTURES = {
    'llms_txt_agent': (),
    'llms_txt_agent_sale': (
        ('product.template', {'name': 'Listing probe product', 'is_published': True}),
    ),
    'llms_txt_agent_blog': (
        ('blog.post', {'name': 'Listing probe article', 'is_published': True}),
    ),
}

# QA-31 audit, claim 8: "served in under 5ms" was printed without a measurement,
# and claim 20's "far more likely to be cited" promised an outcome no test here
# can observe.  Both are numbers/verbs this product cannot evidence, so they are
# banned from the text a buyer reads -- a cached hit is fast, and that is the
# whole of what may be claimed.
HYPE_PATTERNS = (
    ('latency figure', re.compile(r'\b\d+\s?ms\b|\bmicroseconds?\b|\bmilliseconds\b'
                                  r'|\bin under \d+\b|\bblazing\b|\bsub-?\d+\b', re.I)),
    ('outcome promise', re.compile(r'\bmore likely\b|\bmost likely\b|\bguarantee\w*\b'
                                   r'|\bproven\b|\bwill rank\b|\bboost\w*\b', re.I)),
)


def _hype_hits(text):
    """``[(kind, phrase), ...]`` -- the same finder for the listing and the probe."""
    hits = set()
    for kind, pattern in HYPE_PATTERNS:
        for phrase in pattern.findall(text):
            hits.add((kind, phrase.lower()))
    return sorted(hits)


def _manifest_field(module_dir, field):
    with open(os.path.join(module_dir, '__manifest__.py'), encoding='utf-8') as handle:
        return str(ast.literal_eval(handle.read().strip()).get(field, ''))


def _canonical(token):
    """``/llms/page/<id>.md`` and ``/llms/page/<int:page_id>.md`` are one route."""
    return PATH_PARAM.sub('<>', token.strip(TRAILING))


@tagged('post_install', '-at_install')
class TestListingClaims(TransactionCase):

    def _listing_text(self):
        """Every file a buyer reads before paying, minus external URLs."""
        pieces = []
        description = os.path.join(MODULE_DIR, 'static', 'description')
        for name in sorted(os.listdir(description)):
            if name.endswith('.html'):
                with open(os.path.join(description, name), encoding='utf-8') as handle:
                    pieces.append(handle.read())
        with open(os.path.join(MODULE_DIR, 'README.md'), encoding='utf-8') as handle:
            pieces.append(handle.read())
        pieces.append(_manifest_field(MODULE_DIR, 'summary'))
        pieces.append(_manifest_field(MODULE_DIR, 'description'))
        return ABSOLUTE_HOST.sub('', html.unescape('\n'.join(pieces)))

    def _registered_routes(self):
        """Routes this module's own controllers register, canonicalised."""
        mods = sorted({MODULE} | set(
            ast.literal_eval(open(os.path.join(MODULE_DIR, '__manifest__.py'),
                                  encoding='utf-8').read().strip())['depends']))
        converters = self.env['ir.http']._get_converters()
        return {_canonical(url)
                for url, _endpoint in odoo_http._generate_routing_rules(mods, False, converters)
                if url.startswith('/llms')}

    def _advertised_routes(self):
        return {_canonical(token) for token in ROUTE_TOKEN.findall(self._listing_text())}

    def _is_served(self, path, registered):
        """``/llms/page/<id>.md`` is served by the rule ``/llms/page/<int:page_id>.md``."""
        if path in registered:
            return True
        head = path.split('<>')[0]
        return head != path and any(other.split('<>')[0] == head for other in registered)

    def test_every_advertised_endpoint_is_registered(self):
        """QA-31: the listing cannot promise a route the code does not serve."""
        registered = self._registered_routes()
        advertised = self._advertised_routes()
        self.assertTrue(advertised, 'no endpoint is advertised anywhere in the listing')
        invented = sorted(path for path in advertised if not self._is_served(path, registered))
        self.assertEqual(
            invented, [],
            'advertised but not registered by %s: %s (registered: %s)'
            % (MODULE, invented, sorted(registered)))

    def test_no_exports_endpoint_is_advertised(self):
        """The fabricated ``/exports/*.xml|json|txt`` block must never come back."""
        hits = sorted({_canonical(token) for token in ROUTE_TOKEN.findall(self._listing_text())
                       if token.startswith('/exports')})
        self.assertEqual(hits, [], 'listing advertises /exports routes: %s' % hits)

    def test_the_guard_itself_catches_the_original_fabrication(self):
        """A filter that matches nothing is worse than no filter at all.

        Fed the exact markup QA-31 describes, the extractor must still name the
        invented routes -- otherwise the two tests above could pass on empty
        sets forever.
        """
        sample = (
            '<h4>Full Context Export</h4>\n'
            '<ul><li><a href="https://mywebsite.com/exports/context.xml">Context.xml</a></li>\n'
            '<li><a href="https://mywebsite.com/exports/dataset.json">Dataset.json</a></li>\n'
            '<li>[Archive.txt](https://mywebsite.com/exports/archive.txt)</li>\n'
            '<li><code>/llms.txt</code> and <code>/llms/page/&lt;id&gt;.md</code></li></ul>'
        )
        found = {_canonical(token) for token in ROUTE_TOKEN.findall(
            ABSOLUTE_HOST.sub('', html.unescape(sample)))}
        self.assertEqual(found, {
            '/exports/context.xml', '/exports/dataset.json', '/exports/archive.txt',
            '/llms.txt', '/llms/page/<>.md',
        }, 'the listing extractor lost its teeth: %s' % sorted(found))

    def test_every_registered_route_is_advertised(self):
        """The listing must not under-claim either -- a crawler owner who never
        learns about ``/llms.md`` cannot use it."""
        registered = self._registered_routes()
        advertised = self._advertised_routes()
        missing = sorted(path for path in registered if path not in advertised)
        self.assertEqual(missing, [],
                         '%s serves routes the listing never mentions: %s' % (MODULE, missing))

    def test_the_listing_names_screens_that_exist(self):
        """Each label is checked twice: promised by the listing, shipped by the code.

        Checking only the code would let the two lists drift apart, which is how
        QA-31 happened -- the listing described a product that was never built.
        """
        listing = self._listing_text()
        sources = []
        for folder, suffix in (('views', '.xml'), ('models', '.py')):
            root = os.path.join(MODULE_DIR, folder)
            for name in sorted(os.listdir(root)):
                if name.endswith(suffix):
                    with open(os.path.join(root, name), encoding='utf-8') as handle:
                        sources.append(handle.read())
        blob = html.unescape('\n'.join(sources))
        for label in LISTING_UI_LABELS:
            self.assertIn(label, listing,
                          'the test expects the listing to promise %r, and it does not' % label)
            self.assertIn(label, blob,
                          '%r is not a string this module ships' % label)

    def test_the_listing_repeats_the_document_markers_verbatim(self):
        """Headings quoted from the generated file must be what it really emits."""
        for model, vals in LISTING_MARKER_FIXTURES.get(MODULE, ()):
            self.env[model].create(vals)
        website = self.env['website'].search([], limit=1)
        instructions = website.llm_site_instructions
        try:
            website.llm_site_instructions = 'Marker probe for the store listing.'
            document = (website._generate_llms_txt()
                        + '\n' + website._generate_llms_full_txt())
        finally:
            website.llm_site_instructions = instructions
        for marker in LISTING_DOCUMENT_MARKERS:
            self.assertIn(marker, document,
                          '%r is not in the generated document' % marker)

    def test_no_unmeasured_latency_or_outcome_promise_is_printed(self):
        """QA-31 claims 8 and 20: no millisecond figure, no citation guarantee."""
        self.assertEqual(_hype_hits(self._listing_text()), [],
                         '%s sells the product with a claim nothing here can evidence' % MODULE)

    def test_the_hype_filter_catches_the_two_original_sentences(self):
        """Same self-check rule as the route extractor: a silent filter is no guard."""
        sample = ('Pre-cached content served in under 5ms.  Structured content is far '
                  'more likely to be cited, guaranteed, and proven to boost rankings.')
        kinds = {kind for kind, _ in _hype_hits(sample)}
        self.assertEqual(kinds, {'latency figure', 'outcome promise'},
                         'the hype filter matches nothing: %s' % sorted(_hype_hits(sample)))
