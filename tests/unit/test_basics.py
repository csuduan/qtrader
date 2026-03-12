import pytest


@pytest.mark.unit
class TestBasicOperations:
    """基础数学操作测试"""
    
    def test_addition(self):
        """加法测试"""
        assert 1 + 1 == 2
        assert 100 + 200 == 300
    
    def test_subtraction(self):
        """减法测试"""
        assert 10 - 5 == 5
        assert 100 - 50 == 50
    
    def test_multiplication(self):
        """乘法测试"""
        assert 2 * 3 == 6
        assert 10 * 10 == 100
    
    def test_division(self):
        """除法测试"""
        assert 10 / 2 == 5.0
        assert 100 / 10 == 10.0
    
    @pytest.mark.parametrize("a,b,expected", [
        (1, 2, 3),
        (10, 20, 30),
        (100, 200, 300),
    ])
    def test_addition_parameterized(self, a, b, expected):
        """参数化加法测试"""
        assert a + b == expected


@pytest.mark.unit
class TestStringOperations:
    """字符串操作测试"""
    
    def test_string_upper(self):
        """字符串转大写测试"""
        assert "hello".upper() == "HELLO"
        assert "world".upper() == "WORLD"
    
    def test_string_lower(self):
        """字符串转小写测试"""
        assert "HELLO".lower() == "hello"
        assert "WORLD".lower() == "world"
    
    def test_string_concatenation(self):
        """字符串拼接测试"""
        assert "hello" + " " + "world" == "hello world"
        assert "foo" + "bar" == "foobar"


@pytest.mark.unit
class TestListOperations:
    """列表操作测试"""
    
    def test_list_length(self):
        """列表长度测试"""
        assert len([1, 2, 3]) == 3
        assert len([]) == 0
        assert len([1]) == 1
    
    def test_list_append(self):
        """列表追加测试"""
        lst = [1, 2, 3]
        lst.append(4)
        assert lst == [1, 2, 3, 4]
    
    def test_list_index(self):
        """列表索引测试"""
        lst = [10, 20, 30, 40, 50]
        assert lst[0] == 10
        assert lst[2] == 30
        assert lst[-1] == 50
    
    def test_list_slice(self):
        """列表切片测试"""
        lst = [1, 2, 3, 4, 5]
        assert lst[1:3] == [2, 3]
        assert lst[:2] == [1, 2]
        assert lst[3:] == [4, 5]
