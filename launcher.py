"""Capture startup failures, including dependency imports, beside the app."""
import sys
import traceback
from pathlib import Path


if __name__=='__main__':
    try:
        import app
        sys.exit(app.main())
    except Exception:
        root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
        (root/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
        raise
