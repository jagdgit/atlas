"""Mission templates subsystem (Phase A · §A.5).

Reusable, versioned blueprints for missions. ``TemplateService`` seeds the built-ins on boot
and instantiates a template into a concrete Mission + config v1 + worker rows.
"""

from __future__ import annotations

from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.missions.templates.service import TemplateError, TemplateService

__all__ = ["TemplateService", "TemplateError", "BUILTIN_TEMPLATES"]
