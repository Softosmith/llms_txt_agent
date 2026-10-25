# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

"""W8 / QA-39 -- the module directory contains nothing but shippable files.

A buyer downloads this directory, so everything inside it is delivered and
reviewed: the QA pass found ``ASSETS.md`` (the internal store-copy worksheet),
``assets_src/logos/*.zip`` (third-party logos fetched from seeklogo, which is a
trademark problem as well as dead weight) and ~20 ``*.pyc`` per companion
committed into git.

``__pycache__`` is the one artefact this test cannot assert against on disk:
Odoo imports this addon from that directory, so any test run recreates it.  A
guard that is red the moment anything runs is noise, not a guard, so the
bytecode is asserted where it actually matters -- against the file list that
would be packaged (``git ls-files``) -- plus a check that the repo's
``.gitignore`` provably covers it.
"""

import ast
import os
import re
import subprocess

from odoo.tests.common import TransactionCase, tagged

MODULE = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_DIR = os.path.dirname(MODULE_DIR)

SHIPPABLE_DIRS = frozenset({
    'controllers', 'data', 'migrations', 'models', 'security', 'static', 'tests', 'views',
})
SHIPPABLE_FILES = frozenset({
    '__init__.py', '__manifest__.py', 'LICENSE', 'README.md', 'hooks.py',
})

# Filenames that must not appear anywhere in the module, at any depth.
FORBIDDEN_NAMES = frozenset({'ASSETS.md', 'assets_src', '.gitignore', '.git', '.DS_Store',
                             'Thumbs.db'})
FORBIDDEN_SUFFIXES = ('.pyc', '.pyo', '.zip', '.7z', '.rar', '.bak', '.orig', '~')

# Recreated by the interpreter on every import; asserted via git instead.
GENERATED_DIRS = frozenset({'__pycache__'})

# Rule 9: no third-party marks in shipped assets.  Naming the engines in the
# listing text is nominative use and allowed; shipping their logos is not.
TRADEMARK_HINTS = ('chatgpt', 'openai', 'claude', 'anthropic', 'gemini', 'bard',
                   'perplexity', 'copilot', 'grok', 'xai', 'seeklogo', 'apple',
                   'mistral', 'llama', 'deepseek')


@tagged('post_install', '-at_install')
class TestPackaging(TransactionCase):

    def _walk(self):
        """``(relative_path, absolute_path)`` for every file in the module dir."""
        found = []
        for dirpath, dirnames, filenames in os.walk(MODULE_DIR):
            dirnames[:] = [d for d in dirnames if d not in GENERATED_DIRS]
            for name in filenames:
                absolute = os.path.join(dirpath, name)
                found.append((os.path.relpath(absolute, MODULE_DIR).replace('\\', '/'), absolute))
        return sorted(found)

    def _tracked_files(self):
        """The file list a packaged download would carry, or ``None`` without git."""
        if not os.path.isdir(os.path.join(REPO_DIR, '.git')):
            return None
        try:
            out = subprocess.run(
                ['git', '-C', REPO_DIR, 'ls-files', '--', MODULE],
                capture_output=True, text=True, check=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        return [line.strip() for line in out.splitlines() if line.strip()]

    def test_no_junk_files_inside_the_module(self):
        """QA-39: no worksheet, no working-asset folder, no archives, no bytecode."""
        offenders = []
        for relative, _absolute in self._walk():
            parts = relative.split('/')
            if FORBIDDEN_NAMES & set(parts[:-1]) or parts[-1] in FORBIDDEN_NAMES:
                offenders.append(relative)
            elif parts[-1].endswith(FORBIDDEN_SUFFIXES):
                offenders.append(relative)
        self.assertEqual(
            offenders, [],
            'files that must not ship are inside %s/: %s' % (MODULE, offenders))

    def test_every_shipped_file_sits_in_an_expected_directory(self):
        """The manifest loader walks this tree; so must nothing unexpected.

        ``.gitignore`` is on the forbidden list deliberately: base's copy sat
        *inside* the module directory, so a customer download carried the
        vendor's git rules.  Repo-level ignore files belong one level up.
        """
        stray = []
        for relative, _absolute in self._walk():
            parts = relative.split('/')
            if len(parts) == 1:
                if parts[0] not in SHIPPABLE_FILES:
                    stray.append(relative)
            elif parts[0] not in SHIPPABLE_DIRS:
                stray.append(relative)
        self.assertEqual(stray, [], 'files outside the shipped layout: %s' % (stray,))

    def test_license_and_readme_ship(self):
        """QA-30: OPL-1 text and a README in every one of the three addons."""
        for name in ('LICENSE', 'README.md'):
            path = os.path.join(MODULE_DIR, name)
            self.assertTrue(os.path.isfile(path), '%s/%s is missing (QA-30)' % (MODULE, name))
            self.assertGreater(os.path.getsize(path), 500,
                               '%s/%s is a placeholder, not a document' % (MODULE, name))
        with open(os.path.join(MODULE_DIR, 'LICENSE'), encoding='utf-8') as handle:
            self.assertIn('Odoo Proprietary License', handle.read(),
                          'the LICENSE is not the OPL-1 text the manifest declares')

    def _manifest(self):
        with open(os.path.join(MODULE_DIR, '__manifest__.py'), encoding='utf-8') as handle:
            return ast.literal_eval(handle.read().strip())

    def test_manifest_images_all_resolve(self):
        """QA-30: a declared ``images`` entry with no file on disk shows a dead listing."""
        images = self._manifest().get('images')
        self.assertTrue(images, '%s declares no images' % MODULE)
        for relative in images:
            path = os.path.join(MODULE_DIR, relative)
            self.assertTrue(os.path.isfile(path),
                            'manifest images entry does not exist: %s' % relative)
            self.assertGreater(os.path.getsize(path), 2000,
                               'manifest images entry is empty: %s' % relative)

    def test_no_third_party_trademark_asset_is_shipped(self):
        """Rule 9: the seeklogo downloads in ``assets_src/logos`` are gone for good."""
        offenders = [relative for relative, _absolute in self._walk()
                     if any(hint in relative.lower() for hint in TRADEMARK_HINTS)]
        self.assertEqual(offenders, [], 'third-party named asset shipped: %s' % offenders)

    def test_bytecode_is_neither_tracked_nor_ignorable_only_by_accident(self):
        """A ``*.pyc`` must not be able to reach a customer's zip.

        Disk is the wrong place to check (see the module docstring), so this
        asserts the mechanism: nothing under ``__pycache__`` is tracked, and the
        repo's own ``.gitignore`` says so explicitly rather than by omission.
        """
        tracked = self._tracked_files()
        if tracked is None:
            self.skipTest('no git checkout here; the packaging guard needs the vendor repo')
        bytecode = [path for path in tracked
                    if '__pycache__' in path or path.endswith(('.pyc', '.pyo'))]
        self.assertEqual(bytecode, [], 'bytecode is tracked and would ship: %s' % bytecode)

        gitignore = os.path.join(REPO_DIR, '.gitignore')
        self.assertTrue(os.path.isfile(gitignore),
                        '%s has no .gitignore at the repo root' % MODULE)
        with open(gitignore, encoding='utf-8') as handle:
            rules = {line.strip() for line in handle if line.strip() and not line.startswith('#')}
        for rule in ('__pycache__/', '*.py[cod]', 'ASSETS.md'):
            self.assertIn(rule, rules,
                          '%s/.gitignore must ignore %r (found %s)' % (MODULE, rule, sorted(rules)))

    def test_the_store_page_has_an_index_and_an_icon(self):
        """The store page falls back to a generic cube when ``icon.png`` is absent."""
        description = os.path.join(MODULE_DIR, 'static', 'description')
        self.assertTrue(os.path.isdir(description), '%s ships no static/description/' % MODULE)
        for name in ('index.html', 'icon.png'):
            path = os.path.join(description, name)
            self.assertTrue(os.path.isfile(path),
                            '%s/static/description/%s is missing (QA-30)' % (MODULE, name))
            self.assertGreater(os.path.getsize(path), 2000,
                               '%s/static/description/%s is a placeholder' % (MODULE, name))

    def _description_assets(self):
        description = os.path.join(MODULE_DIR, 'static', 'description')
        return sorted(name for name in os.listdir(description)
                      if os.path.isfile(os.path.join(description, name)) and name != 'index.html')

    def test_every_picture_the_listing_shows_is_on_disk(self):
        """A broken ``<img src>`` on the store page is a hole in the listing."""
        with open(os.path.join(MODULE_DIR, 'static', 'description', 'index.html'),
                  encoding='utf-8') as handle:
            listing = handle.read()
        missing = sorted(set(re.findall(r'<img[^>]*\bsrc="([^"/]+)"', listing))
                         - set(self._description_assets()))
        self.assertEqual(missing, [],
                         'index.html shows pictures that are not shipped: %s' % missing)

    def test_no_description_asset_is_shipped_without_being_used(self):
        """QA-31/QA-39: an unreferenced image still reaches every buyer's download.

        ``get_recommended.png`` was exactly that -- it left the listing text when
        the fabricated hero copy went, but stayed in the module and carried four
        third-party logos into the paid archive.  Anything in
        ``static/description`` must therefore be the icon, be shown by
        ``index.html``, or be declared in the manifest ``images`` list.
        """
        with open(os.path.join(MODULE_DIR, 'static', 'description', 'index.html'),
                  encoding='utf-8') as handle:
            listing = handle.read()
        declared = {relative.split('/')[-1] for relative in self._manifest().get('images', [])}
        unused = [name for name in self._description_assets()
                  if name not in declared and name != 'icon.png' and ('"%s"' % name) not in listing]
        self.assertEqual(unused, [],
                         'static/description carries unused files: %s' % unused)

    def test_the_manifest_rst_description_parses_cleanly(self):
        """The manifest ``description`` is reStructuredText, and Odoo does render it.

        ``ir_module_module._compute_description_html``
        (``odoo19/odoo/addons/base/models/ir_module.py:188-209``) takes the
        ``static/description/index.html`` when present and otherwise pipes this
        string through docutils with these same overrides -- which is the path the
        two companions ran on before W8 added their listings, and the path they
        fall back to the moment one is dropped.  A parse error there is a visible
        product defect, so keep the prose clean rather than unpinned.
        """
        import io

        from docutils.core import publish_string

        raw = self._manifest().get('description') or ''
        self.assertTrue(raw.strip(), '%s ships an empty manifest description' % MODULE)
        stream = io.StringIO()
        try:
            publish_string(
                source=raw,
                writer_name='html4css1',
                settings_overrides={
                    'embed_stylesheet': False,
                    'doctitle_xform': False,
                    'output_encoding': 'unicode',
                    'xml_declaration': False,
                    'file_insertion_enabled': False,
                    # docutils wants the numeric levels here, not the names.
                    'report_level': 2,   # WARNING and above
                    'halt_level': 4,     # SEVERE
                    'warning_stream': stream,
                },
            )
        except Exception as exc:      # a SEVERE parse error raises SystemMessage
            stream.write('\n%r' % (exc,))
        self.assertEqual(stream.getvalue().strip(), '',
                         'the manifest description is not valid reStructuredText:\n%s'
                         % stream.getvalue())


