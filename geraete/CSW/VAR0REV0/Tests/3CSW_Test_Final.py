import time

def test_final_multiple_asserts():
    time.sleep(5)
    assert 1 + 1 == 2
    assert "csw".upper() == "CSW"
    assert sorted([3, 1, 2]) == [1, 2, 3]
    assert len("test") == 4
