from __future__ import annotations

import sys

from chopscout.exporter import validate_package

problems = validate_package(sys.argv[1])
print("\n".join(problems) if problems else "Package is valid.")
raise SystemExit(bool(problems))
