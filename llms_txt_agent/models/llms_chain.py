# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

"""Shared generation plumbing for the three llms.txt addons (QA-26).

The product decision behind this family is that ``llms_txt_agent``,
``llms_txt_agent_sale`` and ``llms_txt_agent_blog`` never depend on one another,
so a customer can buy any one of them alone.  The cost of that decision is
duplication: each addon ships its own byte-identical copy of this file (the
companion test suites hash-compare the copies), and any one of the three may be
the only module present when a document is generated.

The consequence Odoo makes unavoidable is the one this file exists to neutralise.
When two or three of the addons are installed, their ``website`` classes are
merged into a single MRO, and the order of that MRO comes from
``sorted(registry._init_modules)`` -- alphabetical by module name, not by
anything the vendor or the customer chooses.  So *which module's implementation
answers* is a property of the install list rather than of the code, and both
defects QA-26 covers follow from that:

``next_hook`` / ``chain_call``
    Walk the merged chain by reading class ``__dict__``s.  The shipped guard was
    ``super().x if hasattr(super(), 'x') else []``, and ``hasattr`` asks the
    *attribute* question: it runs the descriptor and swallows any
    ``AttributeError`` it raises.  A parent implementation that fails while being
    reached therefore looked exactly like "no parent module is installed", and
    the module's whole section quietly disappeared from ``/llms.txt`` instead of
    raising where a maintainer would see it.

``sort_sections``
    Emit the sections in one documented order -- pages, then products, then blog
    articles -- whatever order the MRO collected them in.

Like ``html_to_md.py``, this module deliberately imports nothing from ``odoo``:
it has to be loadable, and unit-testable, without a registry.
"""

# The section headings this family owns, in the order they are guaranteed to
# appear in /llms.txt.  Unknown headings -- a third-party module that extends
# ``_get_llms_txt_sections`` -- are not dropped: they sort after these three and
# keep their relative order (``sorted`` is stable).
SECTION_HEADINGS = (
    '## Website Pages',                  # llms_txt_agent
    '## eCommerce Catalog Products',     # llms_txt_agent_sale
    '## Blog Articles',                  # llms_txt_agent_blog
)


def next_hook(super_proxy, name):
    """Return the next implementation of ``name`` above ``super_proxy``, or ``None``.

    ``super_proxy`` is the ``super()`` of the *calling* method -- zero-argument
    inside a normal method.  Two of its attributes are easy to confuse and both
    are needed:

    ``__thisclass__``
        the class the calling method is defined on.
    ``__self_class__``
        the class the lookup actually starts from.  On a merged Odoo model this
        is the composed registry class -- a *subclass* of ``__thisclass__``, not
        equal to it -- which is why the scan has to be performed on
        ``__self_class__.__mro__`` while being anchored at ``__thisclass__``.

    The first class after that anchor which defines ``name`` in its own
    ``__dict__`` wins, and is returned bound to the caller's instance.  Reading
    ``__dict__`` rather than using ``getattr`` on the proxy is the whole point:
    no ``hasattr``, no swallowed error.  ``None`` means the chain really ends
    here -- the single-module install every companion must support -- and the
    caller supplies its own starting value.
    """
    mro = super_proxy.__self_class__.__mro__
    try:
        anchor = mro.index(super_proxy.__thisclass__)
    except ValueError:
        # Not a usable proxy (a hand-made super() whose first argument is not in
        # the instance's MRO).  Treat it as the end of the chain rather than
        # raising from inside a document-generation helper.
        return None
    instance = getattr(super_proxy, '__self__', None)
    owner = type(instance) if instance is not None else super_proxy.__self_class__
    for klass in mro[anchor + 1:]:
        implementation = klass.__dict__.get(name)
        if implementation is None:
            continue
        bind = getattr(implementation, '__get__', None)
        return implementation if bind is None else bind(instance, owner)
    return None


def chain_call(super_proxy, name, *args, default=None, **kwargs):
    """Call the parent implementation of ``name``, or return ``default``.

    Usage inside one of these addons' hook methods::

        sections = list(chain_call(super(), '_get_llms_txt_sections', base_url,
                                   default=[]))

    ``default`` is handed back as it is, so a caller that mutates the result must
    copy it -- every call site here wraps in ``list(...)`` for that reason.  When
    a parent exists its return value is passed through untouched, so a chain of
    three modules still produces one list, in parent-first order, which
    ``sort_sections`` then re-weights.
    """
    hook = next_hook(super_proxy, name)
    if hook is None:
        return default
    return hook(*args, **kwargs)


def section_weight(section):
    """Sort key for one section: its position in ``SECTION_HEADINGS``, else last."""
    heading = (section or '').split('\n', 1)[0].strip()
    try:
        return SECTION_HEADINGS.index(heading)
    except ValueError:
        return len(SECTION_HEADINGS)


def sort_sections(sections):
    """Return ``sections`` in the documented order, independent of load order.

    On a combined install the chain returns the furthest module's section first,
    and which module that is depends on ``ir_module_module.name`` sorting.  With
    only ``llms_txt_agent`` installed the same call returns one section; with
    only the Blog companion, one *other* section.  Sorting by a fixed table is
    what lets the store listing promise a stable document, and it is a guarantee
    rather than an accident from here on: ``## Website Pages``, then
    ``## eCommerce Catalog Products``, then ``## Blog Articles``, then anything a
    third-party module appends.
    """
    return sorted(sections, key=section_weight)
