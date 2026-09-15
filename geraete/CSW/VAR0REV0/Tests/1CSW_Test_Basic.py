import time


def test_sanity():
    time.sleep(5)
    assert 1 + 1 == 2


class TestCSWBasic:
    def test_placeholder(self):
        assert True
