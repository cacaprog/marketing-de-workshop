import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="agentready-test-")
os.environ["AGENTREADY_DB"] = os.path.join(_tmp, "test.duckdb")
os.environ["AGENTREADY_TRACES"] = os.path.join(_tmp, "traces")

import pytest  # noqa: E402

from agentready import generate, pipeline  # noqa: E402
from agentready.db import connect  # noqa: E402


@pytest.fixture
def con():
    generate.generate()
    pipeline.run()
    c = connect()
    yield c
    c.close()
