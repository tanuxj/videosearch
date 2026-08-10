"""Test-wide setup.

The `APP_ENV` variable must be set before `app.main` is imported (settings
are cached at import time), so it is pinned here at collection time.
"""

import os

os.environ["APP_ENV"] = "test"
