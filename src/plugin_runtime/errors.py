class PluginError(RuntimeError):
    """Base class for trusted local plugin runtime failures."""


class PluginManifestError(PluginError):
    """Raised when a plugin manifest is missing required fields or is invalid."""
