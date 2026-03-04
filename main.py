"""Main executable for RUNI Wiki Tools."""

import sys
from pathlib import Path

# Добавляем папку script/ в sys.path, чтобы корректно импортировались пакеты core и commands
script_dir = Path(__file__).resolve().parent / "script"
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))



from cli import CLIApplication

def main() -> int:
    """Entry point."""
    app = CLIApplication()
    return app.run()

if __name__ == "__main__":
    sys.exit(main())
