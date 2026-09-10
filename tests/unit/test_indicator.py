"""
指标纯函数（indicator）单元测试

对可工作的纯函数用手工计算的小样本断言精确值（含空序列、长度不足、单元素边界）。

注意：当前环境为 numpy 2.x，indicator.py 中 ma/wma/std_dev/ewma/ewma_vectorized/macd/rsi
依赖已被移除的 np.NaN / np.float 或使用 np.array(copy=False) 旧语义，运行即抛异常；
kd 存在数组长度错位的逻辑缺陷。这些函数的期望值测试标记为 xfail（非 strict）：
一旦 src 修复，测试会自动转为 XPASS 提示修复完成。
"""

import math

import numpy as np
import pytest

from qtrader.utils import indicator as ind

# numpy 2.x 移除了 np.NaN/np.float，且 np.array(obj, copy=False) 在需要拷贝时抛错
NUMPY2_BROKEN = "indicator 模块未适配 numpy 2.x（np.NaN/np.float 已移除、copy=False 语义变更）"


@pytest.mark.unit
class TestRolling:
    """滑动窗口视图测试"""

    def test_rolling_windows(self):
        """测试窗口切分结果"""
        result = ind.rolling(np.arange(6.0), 3)
        expected = np.array([[0, 1, 2], [1, 2, 3], [2, 3, 4], [3, 4, 5]], dtype=float)
        assert result.shape == (4, 3)
        assert np.array_equal(result, expected)

    def test_rolling_window_one(self):
        """测试窗口为1时每个元素自成一行"""
        result = ind.rolling(np.arange(3.0), 1)
        assert result.shape == (3, 1)
        assert np.array_equal(result.flatten(), np.arange(3.0))

    def test_rolling_window_equals_length(self):
        """测试窗口等于序列长度时仅一行"""
        result = ind.rolling(np.arange(3.0), 3)
        assert result.shape == (1, 3)
        assert np.array_equal(result[0], np.arange(3.0))

    def test_rolling_window_exceeds_length_raises(self):
        """测试窗口大于序列长度时报错"""
        with pytest.raises(ValueError, match="negative dimensions"):
            ind.rolling(np.arange(3.0), 5)


@pytest.mark.unit
class TestStd:
    """样本标准差测试"""

    def test_std_sample(self):
        """测试样本标准差（ddof=1）：[1,2,3] -> 1.0"""
        assert ind.std([1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_std_constant_zero(self):
        """测试常数序列标准差为0"""
        assert ind.std([4.0, 4.0, 4.0]) == pytest.approx(0.0)

    def test_std_single_element_nan(self):
        """测试单元素序列 ddof=1 无自由度，结果为 NaN"""
        assert math.isnan(ind.std(np.array([5.0])))


@pytest.mark.unit
class TestSma:
    """简单移动平均测试（注意：返回有效窗口结果，不填充 NaN）"""

    def test_sma_basic(self):
        """测试 [1,2,3,4] 窗口2 -> [1.5, 2.5, 3.5]"""
        result = ind.sma([1, 2, 3, 4], 2)
        np.testing.assert_allclose(result, [1.5, 2.5, 3.5])

    def test_sma_window_one_identity(self):
        """测试窗口为1时原样返回"""
        np.testing.assert_allclose(ind.sma([1.0, 2.0, 3.0], 1), [1.0, 2.0, 3.0])

    def test_sma_single_element(self):
        """测试单元素序列窗口1"""
        np.testing.assert_allclose(ind.sma(np.array([5.0]), 1), [5.0])

    def test_sma_empty_raises(self):
        """测试空序列报错"""
        with pytest.raises(ValueError, match="empty"):
            ind.sma(np.array([]), 3)


@pytest.mark.unit
class TestBollingerBands:
    """布林带测试（总体标准差 ddof=0）"""

    def test_bollinger_basic(self):
        """测试 [1..5] 窗口3 2倍标准差：均值4，std=sqrt(2/3)"""
        upper, lower = ind.bollinger_bands([1.0, 2.0, 3.0, 4.0, 5.0], 3, 2)
        std = math.sqrt(2.0 / 3.0)  # [3,4,5] 的总体标准差
        assert upper == pytest.approx(4.0 + 2 * std)
        assert lower == pytest.approx(4.0 - 2 * std)

    def test_bollinger_window_exceeds_length_uses_all(self):
        """测试窗口大于序列长度时静默使用全部数据（均值2，std=sqrt(2/3)）"""
        upper, lower = ind.bollinger_bands([1.0, 2.0, 3.0], 5, 2)
        std = math.sqrt(2.0 / 3.0)
        assert upper == pytest.approx(2.0 + 2 * std)
        assert lower == pytest.approx(2.0 - 2 * std)

    def test_bollinger_empty_returns_nan(self):
        """测试空序列返回 NaN"""
        upper, lower = ind.bollinger_bands([], 3, 2)
        assert math.isnan(upper)
        assert math.isnan(lower)


@pytest.mark.unit
class TestGetMaxRowSize:
    """EWMA 分块行大小计算测试"""

    def test_known_alpha_values(self):
        """测试手工计算值：log(tiny)/log(1-alpha) 取整加1"""
        assert ind.get_max_row_size(0.5) == 1023
        assert ind.get_max_row_size(0.9) == 308

    def test_alpha_out_of_range_raises(self):
        """测试 alpha=1 越界触发断言"""
        with pytest.raises(AssertionError):
            ind.get_max_row_size(1.0)


@pytest.mark.unit
class TestKdj:
    """KDJ 测试（手工逐步推算卷积结果）"""

    def test_kdj_small_sample_exact(self):
        """测试 n=1 手算值

        close/roll 后 min=[2,3,4,5,6], max=[7,5,6,7,8]，RSV=[20,50,50,50,50]；
        K 初值 [50,0,0,0,0]，经两次 "same" 卷积并切片后
        K=[50/9,0,0]，D=[50/27,50/27,0]，J=3K-2D=[350/27,-100/27,0]
        """
        close = np.array([3.0, 4, 5, 6, 7])
        high = np.array([4.0, 5, 6, 7, 8])
        low = np.array([2.0, 3, 4, 5, 6])

        k, d, j = ind.kdj(close, high, low, n=1)

        np.testing.assert_allclose(k, [50 / 9, 0, 0])
        np.testing.assert_allclose(d, [50 / 27, 50 / 27, 0])
        np.testing.assert_allclose(j, [350 / 27, -100 / 27, 0])

    def test_kdj_output_shapes(self):
        """测试输出长度为 len(close)-n-m2+2 且 J=3K-2D"""
        close = np.arange(30.0)
        k, d, j = ind.kdj(close, close + 1, close - 1, n=9)

        assert len(k) == len(d) == len(j) == len(close) - 9 - 3 + 2
        np.testing.assert_allclose(j, 3 * k - 2 * d)


# ==================== 以下函数在 numpy 2.x 下当前损坏，期望值测试标记 xfail ====================


def _ema_ref(values, period: int) -> list[float]:
    """标准 EMA 递推参照实现：e[0]=x[0]，e[i]=alpha*x[i]+(1-alpha)*e[i-1]"""
    alpha = 1.0 - 2.0 / (1.0 + period)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


@pytest.mark.unit
class TestMa:
    """移动平均线测试（前 n-1 个位置填充 NaN）"""

    @pytest.mark.xfail(reason=NUMPY2_BROKEN + "：ma 使用 np.NaN", strict=False)
    def test_ma_basic(self):
        """测试 [1,2,3,4] 窗口2 -> [NaN, 1.5, 2.5, 3.5]（右对齐均值）"""
        result = ind.ma([1, 2, 3, 4], 2)
        assert np.isnan(result[:1]).all()
        np.testing.assert_allclose(result[1:], [1.5, 2.5, 3.5])

    @pytest.mark.xfail(reason=NUMPY2_BROKEN + "：ma 使用 np.NaN", strict=False)
    def test_ma_window_exceeds_length_all_nan(self):
        """测试窗口大于序列长度时输出全 NaN（长度 n-1）"""
        result = ind.ma([1.0, 2.0], 3)
        assert result.shape == (2,)
        assert np.isnan(result).all()

    def test_ma_single_element_window_one(self):
        """测试单元素序列窗口1 -> [5.0]（n=1 时 NaN 填充列表不执行，可用）"""
        np.testing.assert_allclose(ind.ma([5.0], 1), [5.0])


@pytest.mark.unit
class TestWma:
    """加权移动平均测试"""

    @pytest.mark.xfail(reason=NUMPY2_BROKEN + "：wma 使用 np.NAN", strict=False)
    def test_wma_basic(self):
        """测试 [1,2,3,4] 窗口2（权重[2,1]/3）-> [NaN, 4/3, 7/3, 10/3]"""
        result = ind.wma([1, 2, 3, 4], 2)
        assert np.isnan(result[:1]).all()
        np.testing.assert_allclose(result[1:], [4 / 3, 7 / 3, 10 / 3], rtol=1e-6)


@pytest.mark.unit
class TestStdDev:
    """滚动标准差测试"""

    @pytest.mark.xfail(reason=NUMPY2_BROKEN + "：std_dev 依赖 ma", strict=False)
    def test_std_dev_basic(self):
        """测试 [1..5] 窗口2 相邻差恒为0.5 -> [NaN, 0.5, 0.5, 0.5, 0.5]"""
        result = ind.std_dev([1.0, 2.0, 3.0, 4.0, 5.0], 2)
        assert np.isnan(result[:1]).all()
        np.testing.assert_allclose(result[1:], [0.5, 0.5, 0.5, 0.5])


@pytest.mark.unit
class TestEwma:
    """指数移动平均测试"""

    @pytest.mark.xfail(
        reason=NUMPY2_BROKEN + "：ewma 使用 np.float 且 copy=False 抛错", strict=False
    )
    def test_ewma_basic(self):
        """测试 [1,2,3] period=3（alpha=0.5）-> [1, 1.5, 2.25]"""
        np.testing.assert_allclose(ind.ewma(np.array([1.0, 2.0, 3.0]), period=3), [1.0, 1.5, 2.25])

    @pytest.mark.xfail(
        reason=NUMPY2_BROKEN + "：ewma 使用 np.float 且 copy=False 抛错", strict=False
    )
    def test_ewma_constant_series(self):
        """测试常数序列 EMA 恒为常数"""
        np.testing.assert_allclose(ind.ewma(np.array([2.0, 2.0, 2.0, 2.0]), period=5), [2.0] * 4)

    @pytest.mark.xfail(
        reason=NUMPY2_BROKEN + "：ewma 使用 np.float 且 copy=False 抛错", strict=False
    )
    def test_ewma_matches_recursive_definition(self):
        """测试与标准 EMA 递推定义一致"""
        data = np.array([10.0, 11, 12, 13, 12, 11, 10, 9, 10, 11, 12, 13, 14, 15, 14, 13])
        np.testing.assert_allclose(ind.ewma(data, period=6), _ema_ref(data, 6))

    @pytest.mark.xfail(
        reason=NUMPY2_BROKEN + "：ewma 使用 np.float 且 copy=False 抛错", strict=False
    )
    def test_ewma_single_element(self):
        """测试单元素序列返回自身"""
        np.testing.assert_allclose(ind.ewma(np.array([5.0]), period=3), [5.0])


@pytest.mark.unit
class TestMacd:
    """MACD 测试"""

    @pytest.mark.xfail(reason=NUMPY2_BROKEN + "：macd 依赖 ewma", strict=False)
    def test_macd_matches_recursive_definition(self):
        """测试 MACD/信号/柱状值与标准 EMA 递推定义一致"""
        data = [
            10.0,
            11,
            12,
            13,
            12,
            11,
            10,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            14,
            13,
            12,
            11,
            10,
            9,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            17,
        ]
        macd_line, signal, histo = ind.macd(data)

        expected_macd = np.array(_ema_ref(data, 12)) - np.array(_ema_ref(data, 26))
        expected_signal = np.array(_ema_ref(expected_macd, 9))
        np.testing.assert_allclose(macd_line, expected_macd)
        np.testing.assert_allclose(signal, expected_signal)
        np.testing.assert_allclose(histo, expected_macd - expected_signal)


@pytest.mark.unit
class TestRsi:
    """RSI 测试"""

    @pytest.mark.xfail(
        reason="rsi 中 np.where 仅传两个参数（缺第三个），且依赖已损坏的 ewma", strict=False
    )
    def test_rsi_all_up_is_100(self):
        """测试单边上涨序列 RSI 应为 100"""
        result = ind.rsi([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0], 5)
        assert len(result) == 9
        np.testing.assert_allclose(result, [100.0] * 9)

    @pytest.mark.xfail(
        reason="rsi 中 np.where 仅传两个参数（缺第三个），且依赖已损坏的 ewma", strict=False
    )
    def test_rsi_all_down_is_0(self):
        """测试单边下跌序列 RSI 应为 0"""
        result = ind.rsi([10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0], 5)
        np.testing.assert_allclose(result, [0.0] * 9)


@pytest.mark.unit
class TestKd:
    """KD 指标测试"""

    def test_kd_basic(self):
        """测试 [1..6] 周期3 -> K=[100,100,100,100]，D 前2个 NaN，PERC 前4个 NaN"""
        k, perc = ind.kd(np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]), 3)
        # 窗口1: [1,2,3] -> (3-1)/(3-1)*100 = 100
        # 窗口2: [2,3,4] -> (4-2)/(4-2)*100 = 100
        # 窗口3: [3,4,5] -> (5-3)/(5-3)*100 = 100
        # 窗口4: [4,5,6] -> (6-4)/(6-4)*100 = 100
        np.testing.assert_allclose(k, [100.0, 100.0, 100.0, 100.0])
        # d = ma(k,3) 前2个 NaN；perc = ma(d,3) 需3个非NaN值，但d仅2个 → 全NaN
        assert np.isnan(perc).all()
