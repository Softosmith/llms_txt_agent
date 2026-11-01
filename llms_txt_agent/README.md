# LLMs.txt Agent: Website Pages AI SEO for Odoo 19

[![License: OPL-1](https://img.shields.io/badge/License-OPL--1-blue.svg)](LICENSE)
[![Odoo Version](https://img.shields.io/badge/Odoo-19.0-purple.svg)](https://www.odoo.com)
[![Developer](https://img.shields.io/badge/Developed%20By-Asad%20Ali%20%40%20Softosmith-orange.svg)](https://softosmith.com)

Developed by **Asad Ali** at **[Softosmith.com](https://softosmith.com)**.

Publish your Odoo website pages for **ChatGPT**, **Gemini**, **Perplexity**, **Claude**, **Grok**, **Copilot**, and the other AI assistants that crawl the web. The app serves a standards-compliant `/llms.txt`, a full `/llms-full.txt` context export, and clean per-page `.md` Markdown endpoints, so a crawler that arrives reads your published pages instead of your template. Which sources an assistant cites is its own decision — this app only makes yours readable. Depends on the `website` app alone — no eCommerce or Blog setup required.

Running an online store or blog? Our companion standalone apps (**LLMs.txt Agent: eCommerce Products AI SEO** for `website_sale` and **LLMs.txt Agent: Blog & News AI SEO** for `website_blog`) operate independently or combine seamlessly into the same `/llms.txt`.

---

## 🌟 Key Features

* **Automated `/llms.txt` & `/llms-full.txt` Endpoints**: Dynamically generates and serves both files following the `llms.txt` open standard at your website root, `/llms.md` as the same index with Markdown headers, and a Markdown copy of every published page at that page's own URL with `.md` appended — `/<page-url>.md`, so `/about.md` for a page published at `/about` and `/home.md` for the homepage. The older id-based `/llms/page/<id>.md` stays supported.
* **Smart HTML-to-Markdown Parser**: Converts Odoo website HTML pages into clean GitHub-Flavored Markdown, preserving headings, lists, checklists, links, images, visible navigation, and simple tables while retaining complex merged-cell tables as safe HTML and stripping hidden/editor-only content and scripts.
* **Caching & Auto-Sync**: Cached modes pre-build `/llms.txt`, `/llms-full.txt`, and every per-page Markdown document, with scheduled rebuilds (hourly, daily, or real-time) and cache invalidation scoped to the website whose pages you edited.
* **Granular Exclusions & Custom AI Prompts**: Exclude specific pages from AI crawlers or write custom prompt-optimized Markdown descriptions directly on any `website.page` record.
* **Multi-Website & Multi-Language Support**: Configure Site Title, Site Summary, LLM Guidance, and Cache Mode independently per website, with full Odoo translation support.

---

## 🚀 Installation & Configuration

1. Clone or download `llms_txt_agent` into your custom addons directory.
2. Update your Odoo Apps List (**Apps > Update Apps List**).
3. Install **LLMs.txt Agent: Website Pages AI SEO**.
4. Go to **Website > Configuration > Settings**.
5. Under the **AI Search SEO (llms.txt & Markdown)** section:
   - Enable **Enable llms.txt Generation**.
   - Enter your **Site Title**, **Site Summary / Tagline**, and optional **LLM Guidance / Prompt**.
   - Verify **Include Published Website Pages** is checked.
   - Choose your **Generation & Cache Mode** (*Cached (Hourly Rebuild)*, *Cached (Daily Rebuild)*, or *Real-time / Dynamic*).
   - Click **Rebuild Cache Now** or use the **Preview /llms.txt** and **Preview /llms-full.txt** buttons to inspect your live output.

### Upgrading an existing self-hosted installation

Odoo loads Python models and HTTP routes when the server starts. After uploading or pulling a new module version, restart Odoo **before** upgrading the module so Odoo loads the new code and creates any new database fields during the upgrade.

1. Upload or pull the updated module files.
2. Restart the Odoo service.
3. Upgrade `llms_txt_agent` from **Apps**.
4. Go to **Website > Configuration > Settings** and click **Rebuild Cache Now**.

Alternatively, stop the normal Odoo process and run the module upgrade from the command line:

```bash
./odoo-bin -c /path/to/odoo.conf -d DATABASE_NAME \
  -u llms_txt_agent --stop-after-init
```

Then start the normal Odoo service again and click **Rebuild Cache Now**.

> **Short version:** Install the updated files → restart Odoo → upgrade the module → rebuild the cache.

A second restart after the module upgrade is generally unnecessary when Odoo was restarted before upgrading. On Odoo.sh or other managed hosting, deployment normally restarts the Odoo workers automatically, but you must still upgrade the module so any new database fields are created. If an upgrade reports a missing database column, stop Odoo, run the command-line upgrade above, and start Odoo again.

### Important: anonymous access in a multi-database Odoo server

AI crawlers visit `/llms.txt` without logging in, so Odoo must be able to select the correct database from the requested hostname before this module can run.

- **One website database:** set that database in the Odoo server configuration:

  ```ini
  db_name = your_database_name
  ```

- **Multiple website databases:** give every database its own domain or subdomain and configure Odoo's `dbfilter`. For example, when database names match the first part of each hostname:

  ```ini
  dbfilter = ^%d$
  list_db = False
  ```

  This can map `shop.example.com` to database `shop` and `academy.example.com` to database `academy`.

Restart Odoo after changing its server configuration. This is a standard Odoo deployment setting, not a setting inside this module: Odoo must select a database before it can load any database-installed controller. Multiple databases sharing the exact same hostname therefore need domain, subdomain, port, or reverse-proxy routing configured by the server administrator.

---

## 👨‍💻 Developer & Credits

- **Author**: Asad Ali
- **Website**: [https://softosmith.com](https://softosmith.com)
- **Support**: [support@softosmith.com](mailto:support@softosmith.com)

---

## 📄 License

This module is licensed under the [Odoo Proprietary License v1.0 (OPL-1)](LICENSE).
