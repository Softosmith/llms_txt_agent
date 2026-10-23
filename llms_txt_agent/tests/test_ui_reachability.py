# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

"""W4 -- are the advertised per-page controls actually reachable?

QA-12 is a UI defect with a data-shaped proof: the fields and the generated
documents were always correct, but no screen a customer can navigate to ever
showed the two per-page controls, so "Exclude a page from AI crawlers" was a
feature that could only be switched from a shell.

These tests deliberately avoid the browser and assert what the browser would
have to fetch: the *same* view the web client resolves for the screen in
question.  Two traps are worth naming:

* ``website.page.properties`` has **no primary form view for its own model** --
  ``ir.ui.view.default_view()`` returns ``False`` for it, so
  ``get_view(view_type='form')`` hands back an ORM-generated default that lists
  every field automatically.  A test written against that arch would pass while
  the real dialog stayed empty.  The dialog passes
  ``form_view_ref='website.website_page_properties_view_form'`` instead
  (``odoo19/addons/website/static/src/components/dialog/page_properties.js:236``)
  and that is what is reproduced here.
* The same is true of the backend: core's ``website_pages_form_view`` inherits
  cleanly and *is* returned by ``get_view``, yet QA-12's finding stands because
  ``action_website_pages_list`` binds only ``list,kanban`` -- no screen offers
  the form.  So the guard here is on the action, not on the view.
"""

import re

from odoo.tests.common import TransactionCase, tagged

PAGE_PROPERTIES_VIEW_REF = 'website.website_page_properties_view_form'
LLM_PAGE_FIELDS = ('llm_exclude', 'llm_custom_description')


@tagged('post_install', '-at_install')
class TestLlmsUiReachability(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].create({
            'name': 'UI Test Website',
            'domain': 'https://uitypesite.com',
            'llm_enabled': True,
            'llm_site_title': 'UI Test Company',
            'llm_site_summary': 'Pages reachable from the editor screens.',
            'llm_include_pages': True,
            'llm_cache_ttl': 'hourly',
        })
        cls.view_home = cls.env['ir.ui.view'].create({
            'name': 'UI Home View',
            'type': 'qweb',
            'arch': '<t t-name="ui.home"><div><h1>Welcome Home</h1><p>Main content.</p></div></t>',
            'key': 'ui.home',
        })
        cls.page_home = cls.env['website.page'].create({
            'url': '/ui-home',
            'view_id': cls.view_home.id,
            'website_id': cls.website.id,
            'is_published': True,
            'name': 'UI Home Page',
        })

    # -- helpers ---------------------------------------------------------

    def _dialog_arch(self):
        """The arch the frontend fetches for the Page Properties dialog."""
        return self.env['website.page.properties'].sudo().with_context(
            form_view_ref=PAGE_PROPERTIES_VIEW_REF,
        ).get_view(view_type='form')['arch']

    def _field_tag(self, arch, field_name):
        match = re.search(r'<field\b[^>]*name="%s"[^>]*>' % re.escape(field_name), arch)
        self.assertIsNotNone(match, 'field %s is not in the arch' % field_name)
        return match.group(0)

    def _settings_block(self, arch, setting_id):
        start = arch.find('id="%s"' % setting_id)
        self.assertNotEqual(start, -1, '%s is not in the settings form' % setting_id)
        nxt = arch.find('<setting', start + 1)
        return arch[start:nxt if nxt != -1 else len(arch)]

    # -- QA-12: the dialog ------------------------------------------------

    def test_page_properties_dialog_exposes_llm_fields(self):
        """QA-12: the controls must be in the dialog, not just in a model."""
        arch = self._dialog_arch()
        for field in LLM_PAGE_FIELDS:
            self.assertIn(
                'name="%s"' % field, arch,
                '%s is missing from the Page Properties dialog -- that dialog is '
                'the only screen an editor can reach these fields from' % field)

    def test_page_properties_dialog_fields_are_editable(self):
        """Present is not enough: a readonly field is a dead control."""
        arch = self._dialog_arch()
        exclude_tag = self._field_tag(arch, 'llm_exclude')
        self.assertIn(
            'widget="boolean_toggle"', exclude_tag,
            'the advertised single checkbox must render as a toggle')
        for field in LLM_PAGE_FIELDS:
            tag = self._field_tag(arch, field)
            self.assertNotIn(
                'readonly', tag,
                '%s is readonly in the dialog, so an editor cannot change it' % field)

    def test_page_properties_write_through(self):
        """Writing the dialog record must land on the page itself."""
        properties = self.env['website.page.properties'].sudo().create({
            'target_model_id': self.page_home.id,
            'website_id': self.website.id,
        })
        self.assertEqual(properties.llm_exclude, False)
        properties.write({'llm_exclude': True, 'llm_custom_description': 'Written from the dialog.'})
        self.assertTrue(
            self.page_home.llm_exclude,
            'the dialog checkbox does not write through to website.page')
        self.assertEqual(
            self.page_home.llm_custom_description, 'Written from the dialog.')

    def test_page_properties_write_reaches_the_document(self):
        """The control has to change the export, and expire the cache."""
        before = self.website._generate_llms_txt()
        self.assertIn('/ui-home', before)

        properties = self.env['website.page.properties'].sudo().create({
            'target_model_id': self.page_home.id,
            'website_id': self.website.id,
        })
        properties.write({'llm_exclude': True})

        self.assertFalse(
            self.website.llm_txt_cache,
            'excluding a page from the dialog left the cached document warm')
        self.assertNotIn(
            '/ui-home', self.website._generate_llms_txt(),
            'the page is still in the document after the dialog excluded it')

    def test_page_properties_write_restores_the_page(self):
        """The other direction too: un-checking must put the page back."""
        self.page_home.llm_exclude = True
        properties = self.env['website.page.properties'].sudo().create({
            'target_model_id': self.page_home.id,
            'website_id': self.website.id,
        })
        properties.write({'llm_exclude': False})
        self.assertFalse(self.page_home.llm_exclude)
        self.assertIn('/ui-home', self.website._generate_llms_txt())

    # -- QA-12: the backend ----------------------------------------------

    def test_backend_pages_action_offers_a_form(self):
        """Core's Pages action is list,kanban only, so we ship our own.

        A form view that no action references is exactly what QA-12 was.
        """
        action = self.env.ref('llms_txt_agent.llms_txt_pages_action')
        self.assertEqual(action.res_model, 'website.page')
        views = [(view_id, mode) for view_id, mode in action.views]
        modes = [mode for _view_id, mode in views]
        self.assertIn('form', modes, '%s cannot open a form' % action.name)

        form_view_id = next(view_id for view_id, mode in views if mode == 'form')
        arch = self.env['website.page'].sudo().get_view(
            view_id=form_view_id or None, view_type='form')['arch']
        for field in LLM_PAGE_FIELDS:
            self.assertIn('name="%s"' % field, arch)

    def test_backend_pages_action_rows_open_the_form(self):
        """Core's list sets ``action="open_website_url"``, which is a dead end."""
        action = self.env.ref('llms_txt_agent.llms_txt_pages_action')
        list_view_id = next(
            view_id for view_id, mode in action.views if mode == 'list')
        self.assertTrue(
            list_view_id,
            "the action must bind its own list view, not inherit core's "
            'open_website_url behaviour')
        arch = self.env['website.page'].sudo().get_view(
            view_id=list_view_id, view_type='list')['arch']
        self.assertNotIn(
            'open_website_url', arch,
            'clicking a row must open the settings form, not the public page')
        self.assertIn('name="llm_exclude"', arch, 'the exclusion flag should be visible in the list')

    def test_backend_pages_list_is_not_the_default_list_view(self):
        """Our list is bound by id; it must not hijack every other screen.

        ``ir.ui.view.default_view()`` returns the *lowest* priority view for a
        model and type, so an unthinking small ``priority`` here would quietly
        replace core's Pages list wherever a default is resolved.
        """
        own = self.env.ref('llms_txt_agent.llms_txt_pages_tree_view')
        core = self.env.ref('website.website_pages_tree_view')
        default_id = self.env['ir.ui.view'].sudo().default_view('website.page', 'list')
        self.assertEqual(
            default_id, core.id,
            'the module changed which list view Odoo picks by default')
        self.assertGreater(own.priority, core.priority)

    def test_backend_pages_menu_is_restricted_to_page_editors(self):
        """``website.page`` is only readable by website designers in core."""
        menu = self.env.ref('llms_txt_agent.llms_txt_pages_menu')
        action = self.env.ref('llms_txt_agent.llms_txt_pages_action')
        self.assertEqual(menu.action, action)
        self.assertTrue(
            menu.group_ids,
            'a menu nobody can read is worse than no menu: website.page has no '
            'ACL for plain employees, so the menu must be group-restricted')
        designer = self.env.ref('website.group_website_designer')
        self.assertIn(
            designer, menu.group_ids,
            'the menu must be reachable by the group that can write website.page')

    # -- QA-40: the timestamp refreshes ----------------------------------

    def test_rebuild_action_triggers_a_reload(self):
        """D-J: the toast appeared but "Cache Last Rebuilt" stayed stale."""
        settings = self.env['res.config.settings'].create({
            'website_id': self.website.id,
        })
        action = settings.action_rebuild_llms_cache()
        params = action.get('params') or {}
        self.assertEqual(
            (params.get('next') or {}).get('tag'), 'reload',
            'the settings screen is never told to re-read its related field, so '
            'the timestamp the user just changed keeps showing the old value')
        self.assertEqual(action['tag'], 'display_notification')

    def test_rebuild_action_on_website_records_too(self):
        """The website record is the shared code path for all three buttons."""
        action = self.website.action_rebuild_llms_cache()
        self.assertEqual(
            ((action.get('params') or {}).get('next') or {}).get('tag'), 'reload')
        self.assertTrue(
            self.website.llm_txt_cache,
            'rebuilding must still warm the cache')

    # -- QA-35: no view-validation warnings from our anchors --------------

    def test_settings_preview_anchors_declare_role_button(self):
        """``<a class="btn">`` without ``role`` fails Odoo 19 view validation.

        The warning is what QA-35 is about; asserting on the fetched arch is the
        deterministic half of it (the log-scanning half needs a live install).
        """
        arch = self.env['res.config.settings'].sudo().get_view(view_type='form')['arch']
        block = self._settings_block(arch, 'website_llms_txt_setting')
        anchors = re.findall(r'<a\b[^>]*>', block)
        self.assertEqual(
            len(anchors), 2,
            'expected the two /llms.txt preview anchors in the settings block')
        for tag in anchors:
            self.assertIn(
                'role="button"', tag,
                'a preview anchor is missing its explicit role: %s' % tag)
