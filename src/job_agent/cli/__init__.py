"""Public command-line entry point for the job agent."""


def main() -> None:
    from job_agent.cli.host import main as host_main

    host_main()


__all__ = ["main"]
