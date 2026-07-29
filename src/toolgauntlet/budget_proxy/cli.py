"""ToolGauntlet budget-proxy command-line entry point."""

from agent_chaos.budget_proxy.cli import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
