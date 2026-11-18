"""Install backends sharing one prepare → vendor-action → verify shape.

npm_global covers every discovered npm --global --prefix tool. Other backends
(app bundles, native installers) stay as engine methods until they need the
same shared prep helpers; new backends should land here instead of growing
role-specific branches in engine.install_one.
"""

from . import npm_global
from .base import bounded_rmtree, bounded_unlink, resolve_under

__all__ = [
    "bounded_rmtree",
    "bounded_unlink",
    "npm_global",
    "resolve_under",
]
