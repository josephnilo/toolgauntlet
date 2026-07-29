class AgentChaosError(Exception):
    """Base class for package exceptions."""


class SuiteLoadError(AgentChaosError):
    """Raised when a suite cannot be loaded or validated."""


class ToolTimeoutError(AgentChaosError):
    """Injected timeout error."""


class ToolNetworkError(AgentChaosError):
    """Injected transient network error."""


class PackVerificationError(AgentChaosError):
    """Raised when a signed pack cannot be verified."""
