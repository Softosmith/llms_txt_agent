# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

{
    'name': 'LLMs.txt Agent: Website Pages AI SEO (GEO/AEO for ChatGPT, Gemini, Perplexity)',
    'version': '19.0.1.1.0',
    'category': 'Website/Website',
    'summary': 'Publish your website pages as AI SEO / GEO / AEO llms.txt & Markdown that ChatGPT, Gemini and Perplexity can read.',
    'description': """
LLMs.txt Agent: Website Pages AI SEO
====================================
Everything you need to publish your Odoo website pages for ChatGPT, Gemini,
Perplexity, Claude, Grok, Copilot, Apple Intelligence, and the other LLMs and AI
assistants that crawl the web. One-click AI SEO (GEO / AEO)
for Odoo: automatically publish a standards-compliant `llms.txt`, a full `llms-full.txt`
context export, and clean per-page Markdown endpoints that AI crawlers can actually read.

100% Standalone Website Solution:
---------------------------------
Built specifically for Odoo **Website** pages, content, and landing pages. Requires
only the Odoo `website` app — zero eCommerce or Blog setup required.

If you also run an online store or blog, our companion standalone apps:
- **LLMs.txt Agent: eCommerce Products AI SEO** (for `website_sale` product catalogs)
- **LLMs.txt Agent: Blog & News AI SEO** (for `website_blog` articles)
operate 100% independently or combine seamlessly into the same `/llms.txt` without any mutual dependencies.

Why AI SEO (GEO/AEO) matters now:
----------------------------------
Shoppers and site visitors increasingly ask ChatGPT, Gemini, Perplexity, and Copilot
for recommendations instead of clicking through search results. These AI assistants
can't run your JavaScript or click "read more" — they need clean, structured,
machine-readable text. If your Odoo site doesn't offer it, you get skipped or
misquoted. This app follows the emerging `llms.txt` open standard (think robots.txt +
sitemap.xml, but written for LLMs) so every AI crawler gets what it needs to read
your site as you wrote it.

Key Features:
-------------
* **1-Click Setup**: Enable AI Search SEO from Website Settings and your `/llms.txt`
  is served from your website root — the cache is warmed during installation, so the
  first anonymous crawler request is answered rather than rejected. No manual file
  uploads, no separate hosting.
* **Automated /llms.txt & /llms-full.txt Endpoints**: Dynamically generates and serves
  both files adhering to the official `llms.txt` standard specification, so AI tools
  such as ChatGPT, Gemini, Perplexity, Claude, Grok, and Copilot can discover your site.
* **Automatic Sync**: Content stays fresh — the cache rebuilds automatically on a
  schedule (hourly, daily, or real-time) or instantly whenever website pages are
  created, published, or edited.
* **Smart HTML-to-Markdown Parser**: Converts Odoo Website HTML pages and landing
  pages into clean GitHub-Flavored Markdown that AI models parse and extract
  exact answers from instead of guessing.
* **Caching**: Cached modes answer a crawler from the pre-built document instead of
  regenerating the whole export on every request, and the rebuild schedule follows the
  mode you picked.
* **Granular Exclusions & Prompt Tuning**: Exclude specific website pages
  from AI crawlers, or write custom prompt-optimized descriptions per page.
* **Backend Settings & Instant Preview**: Integrated Website Configuration panel with
  direct preview links and a manual "Rebuild Cache Now" button.
* **Multi-Website Support**: Independent configuration per website in multi-website
  and multi-company Odoo databases.
* **Multi-Language Support**: Site title, summary, LLM guidance, and per-page AI
  descriptions are fully translatable with Odoo's standard translation tools — AI
  crawlers reading a translated page get the matching translated content.
* **Written for AI Readers**: AI assistants are handed structured, noise-free Markdown
  rather than raw HTML, so what they read is what you published.

Keywords: llms.txt, llms.txt generator, AI SEO, GEO, Generative Engine Optimization,
AEO, Answer Engine Optimization, AI visibility, AI search, get indexed by AI, ChatGPT
SEO, Gemini SEO, Perplexity SEO, Claude SEO, Grok SEO, Copilot SEO, AI crawler,
AI sitemap, markdown export, Odoo website SEO, website pages AI SEO,
LLM discovery, multilingual AI SEO.

Developed by Asad Ali at Softosmith (https://softosmith.com).
    """,
    'author': 'Asad Ali (Softosmith)',
    'website': 'https://softosmith.com',
    'support': 'support@softosmith.com',
    'license': 'OPL-1',
    'price': 20.00,
    'currency': 'USD',
    'depends': [
        'website',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/website_page_views.xml',
        'views/website_page_properties_views.xml',
    ],
    'images': [
        'static/description/banner.png',
        'static/description/screenshot_settings.png',
        'static/description/screenshot_page_control.png',
        'static/description/screenshot_pages_list.png',
        'static/description/screenshot_output.png',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': '_post_init_hook',
}
