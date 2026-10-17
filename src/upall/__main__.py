"""Installed console entry point and python -m upall."""
import sys


def entrypoint():
    if sys.platform == "win32":
        print("UPALL currently supports macOS and POSIX terminals, not native Windows.", file=sys.stderr)
        return 2
    try:
        from .cli import main
        return main()
    except BrokenPipeError:
        return 1
    except OSError as error:
        print(f"upall: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
