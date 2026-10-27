"""The real speech engines. Imported only by the CLI and scripts, never by logic modules
(an architecture test checks it), so tests and CI never load a model."""

from __future__ import annotations
