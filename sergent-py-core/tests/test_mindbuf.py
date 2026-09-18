from __future__ import annotations

import sergent_py_core.mindbuf as mindbuf


def test_mindbuf_base_is_noop() -> None:
    assert mindbuf.MindBuf().export() == ""
