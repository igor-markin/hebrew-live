"""Minimal PyInstaller entry point; keep imports before freeze_support trivial."""
import multiprocessing
import sys


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--desktop-control" in sys.argv:
        from hebrew_live.desktop_control import main

        raise SystemExit(main(sys.argv[1:]))
    else:
        from hebrew_live.desktop_runtime import main

        raise SystemExit(main())
