"""ToolGauntlet command-line entry point."""

from agent_chaos.cli import build_parser, main

__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
