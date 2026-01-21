import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any

# 数值计算精度控制
EPS = 1e-12

def roll_mean_right(x: pd.Series, n: int) -> pd.Series:
    '''
    右对齐滚动均值（忽略非有限值，窗口必须成型）
    
    参数:
        x: 输入序列
        n: 滚动窗口大小
        
    返回:
        右对齐的滚动均值序列，非有限值被忽略
        
    算法说明:
        1. 将输入序列转换为数值数组，处理非数值为NaN
        2. 使用累积和技巧高效计算滚动均值
        3. 只计算窗口内有效（有限）值的均值
        4. 窗口必须完全形成（即至少n个有效值）
    '''
    # 转换为数值数组，处理非数值
    a = pd.to_numeric(x, errors="coerce").to_numpy(dtype=float)
    L = a.shape[0]
    out = np.full(L, np.nan, dtype=float)
    
    # 边界条件处理
    if n <= 0:
        return pd.Series(out, index=x.index)
    if n == 1:
        return pd.Series(a, index=x.index)
    
    # 识别有效（有限）值
    finite_mask = np.isfinite(a)
    a2 = np.where(finite_mask, a, 0.0)  # 非有限值替换为0
    
    # 计算累积和和累积计数
    cs = np.concatenate(([0.0], np.cumsum(a2)))
    cn = np.concatenate(([0], np.cumsum(finite_mask.astype(int))))
    
    # 计算每个位置的滚动均值
    for i in range(L):
        j0 = i - n + 1  # 窗口起始位置
        if j0 < 0:  # 窗口未完全形成
            continue
        s = cs[i + 1] - cs[j0]  # 窗口内数值和
        k = cn[i + 1] - cn[j0]  # 窗口内有效值数量
        if k <= 0:  # 窗口内无有效值
            continue
        out[i] = s / k  # 计算均值
    
    return pd.Series(out, index=x.index)

def calc_rsi_sma(close: pd.Series, n: int) -> pd.Series:
    '''
    使用 SMA 口径的 RSI (相对强弱指数)
    
    参数:
        close: 收盘价序列
        n: RSI计算周期
        
    返回:
        RSI值序列，范围[0, 100]
        
    算法说明:
        1. 计算价格变动: d = close.diff()
        2. 分离上涨和下跌幅度: U = max(d, 0), D = max(-d, 0)
        3. 计算上涨和下跌的SMA: AU = SMA(U, n), AD = SMA(D, n)
        4. 计算相对强度: RS = AU / AD
        5. 转换为RSI: RSI = 100 * RS / (1 + RS)
    '''
    # 转换为数值并计算价格变动
    c = pd.to_numeric(close, errors="coerce")
    d = c.diff()
    
    # 分离上涨和下跌幅度
    U = np.maximum(d, 0)  # 上涨幅度
    D = np.maximum(-d, 0)  # 下跌幅度
    
    # 计算上涨和下跌的滚动均值
    AU = roll_mean_right(pd.Series(U, index=close.index), n)  # 平均上涨
    AD = roll_mean_right(pd.Series(D, index=close.index), n)  # 平均下跌
    
    # 计算相对强度，避免除零
    RS = AU / np.maximum(AD, EPS)
    
    # 转换为RSI值
    return 100.0 * RS / (1.0 + RS)

def load_mix_sig_lag1(signal_csv: str, sig_col: str = "sig_tier3") -> pd.DataFrame:
    '''
    外部日频信号读取并按产品生成 sig_ext_lag1 (滞后一期的外部信号)
    
    参数:
        signal_csv: 信号CSV文件路径
        sig_col: 信号列名，默认为 "sig_tier3"
        
    返回:
        包含产品、日期和滞后一期信号的DataFrame
        
    处理流程:
        1. 读取CSV文件
        2. 验证必需列存在: date, product, sig_col
        3. 转换日期格式为整数YYYYMMDD
        4. 按产品和日期排序
        5. 对每个产品的信号进行滞后一期处理
        6. 返回每个产品-日期组合的最新滞后信号
    '''
    # 读取CSV文件
    x = pd.read_csv(signal_csv)
    
    # 验证必需列存在
    need = {"date", "product", sig_col}
    if not need.issubset(set(x.columns)):
        raise ValueError(f"signal_csv must contain columns: date, product, {sig_col}\nFound: {', '.join(x.columns)}")
    
    # 日期格式转换和处理
    x["date_int"] = pd.to_datetime(x["date"]).dt.strftime("%Y%m%d").astype(int)
    x["product"] = x["product"].astype(str)
    x["sig_ext"] = pd.to_numeric(x[sig_col], errors="coerce")
    
    # 按产品和日期排序
    x = x.sort_values(["product", "date_int"])
    
    # 对每个产品的信号进行滞后一期处理
    x["sig_ext_lag1"] = x.groupby("product")["sig_ext"].shift(1)
    
    # 返回每个产品-日期组合的最新滞后信号
    out = (
        x.groupby(["product", "date_int"], as_index=False)["sig_ext_lag1"]
        .last()
    )
    return out

def _parse_hhmmss_to_minutes(s: pd.Series) -> pd.Series:
    '''
    将HH:MM:SS时间字符串转换为分钟数
    
    参数:
        s: 包含时间字符串的Series，格式为 "HH:MM:SS"
        
    返回:
        转换为分钟数的Series
        
    示例:
        "09:30:00" -> 570 (9*60 + 30)
        "13:45:00" -> 825 (13*60 + 45)
    '''
    # 提取小时和分钟部分
    hh = s.str.slice(0, 2).astype(int)  # 小时部分
    mm = s.str.slice(3, 5).astype(int)  # 分钟部分
    
    # 转换为总分钟数
    return hh * 60 + mm

def resample_k_multi_anchor(dt: pd.DataFrame, k_min: int, day_start: str = "09:30:00") -> pd.DataFrame:
    '''
    按锚点时间将 1min 重采样为 K 分钟，OHLC 聚合
    
    参数:
        dt: 包含分钟级数据的DataFrame
        k_min: 重采样周期（分钟）
        day_start: 交易日开始时间，默认为 "09:30:00"
        
    返回:
        重采样后的K分钟级OHLC数据
        
    处理流程:
        1. 按产品、日期、时间排序
        2. 计算每个时间点的日内分钟数
        3. 基于锚点时间计算相对分钟索引
        4. 按K分钟周期分组聚合OHLC数据
        5. 返回重采样后的数据
        
    注意:
        - 锚点时间用于确保每个交易日的K线对齐
        - 只保留交易日开始时间之后的数据
    '''
    d = dt.copy()
    # 按产品、日期、时间排序
    d = d.sort_values(["product", "date_int", "TIMEOFDAY"])
    
    # 计算日内分钟数
    hh = d["TIMEOFDAY"].str.slice(0, 2).astype(int)
    mm = d["TIMEOFDAY"].str.slice(3, 5).astype(int)
    d["minute_of_day"] = hh * 60 + mm
    
    # 计算锚点时间的分钟数
    sh = int(day_start[:2])
    sm = int(day_start[3:5])
    start_min = sh * 60 + sm
    
    # 计算相对于锚点时间的分钟索引
    d["min_idx"] = d["minute_of_day"] - start_min
    d = d[d["min_idx"] >= 0]  # 只保留交易日开始后的数据
    
    # 计算K分钟周期索引
    d["k_idx"] = (d["min_idx"] // k_min).astype(int)
    
    # 按K分钟周期聚合OHLC数据
    agg = (
        d.groupby(["product", "date_int", "k_idx"], as_index=False)
        .agg(
            TIMEOFDAY_open=("TIMEOFDAY", "first"),  # 周期开始时间
            open=("open", "first"),                 # 开盘价
            high=("high", "max"),                   # 最高价
            low=("low", "min"),                     # 最低价
            close=("close", "last"),                # 收盘价
        )
    )
    return agg

def run_rsi_ls_intraday_multi(
    min_df: pd.DataFrame,
    products: Optional[List[str]] = None,
    day_start: str = "09:30:00",
    rsi_n: int = 11,
    short_k: int = 5,
    long_k: int = 15,
    L: float = 50.0,
    S: float = 80.0,
    t_start: str = "10:00:00",
    t_end: str = "13:30:00",
    force_exit: str = "15:00:00",
    tp_ret: float = 0.02,
    sl_ret: float = 0.02,
    fee_rate: float = 0.0,
    one_trade_per_day: bool = True,
    force_fill: str = "open_lastbar",
    signal_csv: Optional[str] = None,
    sig_col: str = "sig_tier3",
    dir_thr: float = 0.10,
) -> Dict[str, Any]:
    '''
    主策略（RSI 短长K与方向过滤、限交易窗口、次日开仓、TP/SL、强制平仓、单日单笔限制），返回 {"k_short", "trades", "daily"}
    '''
    d = min_df.copy()
    need = {"open", "close", "high", "low", "product", "TIMEOFDAY", "date"}
    miss = list(need - set(d.columns))
    if miss:
        raise ValueError(f"min_df missing columns: {', '.join(miss)}")
    if np.issubdtype(d["date"].dtype, np.datetime64):
        d["date_int"] = pd.to_datetime(d["date"]).dt.strftime("%Y%m%d").astype(int)
    else:
        di = pd.to_datetime(d["date"].astype(str), errors="coerce").dt.strftime("%Y%m%d")
        d["date_int"] = di.fillna(d["date"].astype(str).str.replace("-", "", regex=False)).astype(int)
    d["product"] = d["product"].astype(str)
    d["TIMEOFDAY"] = d["TIMEOFDAY"].astype(str)
    d = d[np.isfinite(d["open"]) & np.isfinite(d["close"]) & np.isfinite(d["high"]) & np.isfinite(d["low"])]
    if products is not None:
        d = d[d["product"].isin(products)]
    if d.shape[0] == 0:
        raise ValueError("No data after filtering products/date.")
    kS = resample_k_multi_anchor(d, short_k, day_start=day_start)
    kL = resample_k_multi_anchor(d, long_k, day_start=day_start)
    kS = kS.sort_values(["product", "date_int", "k_idx"])
    kL = kL.sort_values(["product", "date_int", "k_idx"])
    kS["rsi_s"] = (
        kS.groupby("product", group_keys=False)["close"]
        .apply(lambda s: calc_rsi_sma(s, rsi_n))
    )
    kL["rsi_l"] = (
        kL.groupby("product", group_keys=False)["close"]
        .apply(lambda s: calc_rsi_sma(s, rsi_n))
    )
    mult = int(long_k / short_k)
    if mult <= 0 or (long_k % short_k) != 0:
        raise ValueError("long_k must be a multiple of short_k")
    kS["kL_idx"] = (kS["k_idx"] // mult).astype(int)
    kS = kS.merge(
        kL[["product", "date_int", "k_idx", "rsi_l"]],
        left_on=["product", "date_int", "kL_idx"],
        right_on=["product", "date_int", "k_idx"],
        how="left",
        sort=False,
        suffixes=("", "_drop"),
    ).drop(columns=["k_idx_drop"])
    if signal_csv is not None and len(str(signal_csv)) > 0:
        sig_ext = load_mix_sig_lag1(signal_csv, sig_col=sig_col)
        kS = kS.merge(sig_ext, on=["product", "date_int"], how="left", sort=False)
    else:
        kS["sig_ext_lag1"] = np.nan
    kS["in_window"] = (kS["TIMEOFDAY_open"] >= t_start) & (kS["TIMEOFDAY_open"] < t_end)
    kS["sig"] = 0
    mask_long = kS["in_window"] & np.isfinite(kS["rsi_l"]) & np.isfinite(kS["rsi_s"]) & (kS["rsi_l"] > L) & (kS["rsi_s"] > S)
    mask_short = kS["in_window"] & np.isfinite(kS["rsi_l"]) & np.isfinite(kS["rsi_s"]) & (kS["rsi_l"] < (100 - L)) & (kS["rsi_s"] < (100 - S))
    kS.loc[mask_long, "sig"] = 1
    kS.loc[mask_short, "sig"] = -1
    if signal_csv is not None and len(str(signal_csv)) > 0:
        thr = float(dir_thr)
        cond_pos = np.isfinite(kS["sig_ext_lag1"]) & (kS["sig_ext_lag1"] >= thr)
        cond_neg = np.isfinite(kS["sig_ext_lag1"]) & (kS["sig_ext_lag1"] <= -thr)
        kS["ext_dir"] = np.where(cond_pos, 1, np.where(cond_neg, -1, 0)).astype(int)
        kS.loc[(kS["sig"] == 1) & (kS["ext_dir"] != 1), "sig"] = 0
        kS.loc[(kS["sig"] == -1) & (kS["ext_dir"] != -1), "sig"] = 0
        kS.loc[kS["ext_dir"] == 0, "sig"] = 0
    else:
        kS["ext_dir"] = 0
    kS["entry_sig"] = (
        kS.groupby(["product", "date_int"])["sig"]
        .shift(1)
        .fillna(0)
        .astype(int)
    )
    kS.loc[kS["TIMEOFDAY_open"] >= t_end, "entry_sig"] = 0
    if one_trade_per_day:
        tmp = kS["entry_sig"] != 0
        kS.loc[tmp, "entry_rank"] = kS.loc[tmp].groupby(["product", "date_int"]).cumcount() + 1
        kS.loc[~tmp | (kS["entry_rank"] > 1), "entry_sig"] = 0
        kS.drop(columns=["entry_rank"], inplace=True)
    trades = []
    keys = kS[["product", "date_int"]].drop_duplicates()
    for _, row in keys.iterrows():
        p = row["product"]
        d = int(row["date_int"])
        day = kS[(kS["product"] == p) & (kS["date_int"] == d)]
        holding = False
        side = 0
        entry_px = np.nan
        entry_tod = None
        for i in range(day.shape[0]):
            tod_open = day["TIMEOFDAY_open"].iloc[i]
            if holding and tod_open >= force_exit:
                if force_fill == "close_force":
                    exit_px = float(day["close"].iloc[i])
                    exit_time = force_exit
                else:
                    exit_px = float(day["open"].iloc[i])
                    exit_time = tod_open
                ret_gross = side * (exit_px / entry_px - 1.0)
                ret_net = ret_gross - fee_rate
                trades.append(
                    {
                        "trade_id": len(trades) + 1,
                        "product": p,
                        "date_int": d,
                        "side": side,
                        "entry_time": entry_tod,
                        "entry_px": entry_px,
                        "exit_time": exit_time,
                        "exit_px": exit_px,
                        "exit_reason": "FORCE",
                        "ret_gross": ret_gross,
                        "ret_net": ret_net,
                    }
                )
                holding = False
                side = 0
                continue
            if (not holding) and int(day["entry_sig"].iloc[i]) != 0:
                holding = True
                side = int(day["entry_sig"].iloc[i])
                entry_px = float(day["open"].iloc[i])
                entry_tod = tod_open
                continue
            if holding:
                px = float(day["close"].iloc[i])
                ret_now = side * (px / entry_px - 1.0)
                if np.isfinite(ret_now) and (ret_now >= tp_ret):
                    ret_gross = side * (px / entry_px - 1.0)
                    ret_net = ret_gross - fee_rate
                    trades.append(
                        {
                            "trade_id": len(trades) + 1,
                            "product": p,
                            "date_int": d,
                            "side": side,
                            "entry_time": entry_tod,
                            "entry_px": entry_px,
                            "exit_time": tod_open,
                            "exit_px": px,
                            "exit_reason": "TP",
                            "ret_gross": ret_gross,
                            "ret_net": ret_net,
                        }
                    )
                    holding = False
                    side = 0
                    continue
                if np.isfinite(ret_now) and (ret_now <= -sl_ret):
                    ret_gross = side * (px / entry_px - 1.0)
                    ret_net = ret_gross - fee_rate
                    trades.append(
                        {
                            "trade_id": len(trades) + 1,
                            "product": p,
                            "date_int": d,
                            "side": side,
                            "entry_time": entry_tod,
                            "entry_px": entry_px,
                            "exit_time": tod_open,
                            "exit_px": px,
                            "exit_reason": "SL",
                            "ret_gross": ret_gross,
                            "ret_net": ret_net,
                        }
                    )
                    holding = False
                    side = 0
                    continue
        if holding:
            if force_fill == "close_force":
                exit_px = float(day["close"].iloc[-1])
                exit_time = force_exit
            else:
                exit_px = float(day["open"].iloc[-1])
                exit_time = day["TIMEOFDAY_open"].iloc[-1]
            ret_gross = side * (exit_px / entry_px - 1.0)
            ret_net = ret_gross - fee_rate
            trades.append(
                {
                    "trade_id": len(trades) + 1,
                    "product": p,
                    "date_int": d,
                    "side": side,
                    "entry_time": entry_tod,
                    "entry_px": entry_px,
                    "exit_time": exit_time,
                    "exit_px": exit_px,
                    "exit_reason": "FORCE",
                    "ret_gross": ret_gross,
                    "ret_net": ret_net,
                }
            )
    trades_dt = pd.DataFrame(trades)
    if trades_dt.shape[0] == 0:
        trades_dt = pd.DataFrame(columns=["trade_id","product","date_int","side","entry_time","entry_px","exit_time","exit_px","exit_reason","ret_gross","ret_net"])
    daily = trades_dt.groupby(["product", "date_int"], as_index=False)["ret_net"].sum()
    daily = daily.rename(columns={"ret_net": "pnl"})
    daily = daily.sort_values(["product", "date_int"])
    daily["nav"] = daily.groupby("product")["pnl"].cumsum() + 1.0
    return {"k_short": kS, "trades": trades_dt, "daily": daily}

def calc_perf_from_daily(daily_dt: pd.DataFrame, product: str) -> Optional[Dict[str, Any]]:
    d = daily_dt.copy()
    prod = str(product)
    d = d[d["product"] == prod]
    if d.shape[0] == 0:
        return None
    d = d.sort_values("date_int")
    ret = d["pnl"].to_numpy()
    nav = d["nav"].to_numpy()
    n = d.shape[0]
    if n < 20:
        return {"n": n, "ann_ret": np.nan, "ann_vol": np.nan, "sharpe": np.nan, "max_dd": np.nan, "win_rate": np.nan, "nav_last": float(nav[-1])}
    ann_ret = float(nav[-1]) ** (252.0 / n) - 1.0
    ann_vol = float(np.nanstd(ret)) * np.sqrt(252.0)
    sharpe = ann_ret / ann_vol if np.isfinite(ann_vol) and ann_vol > 0 else np.nan
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1.0
    max_dd = float(np.nanmin(dd))
    win_rate = float(np.nanmean(ret > 0))
    return {"n": n, "ann_ret": ann_ret, "ann_vol": ann_vol, "sharpe": sharpe, "max_dd": max_dd, "win_rate": win_rate, "nav_last": float(nav[-1])}

def grid_scan_rsi(
    min_df: pd.DataFrame,
    product: str = "IM",
    grid: pd.DataFrame = None,
    day_start: str = "09:30:00",
    short_k: int = 5,
    long_k: int = 15,
    t_start: str = "10:00:00",
    force_exit: str = "15:00:00",
    force_fill: str = "open_lastbar",
    one_trade_per_day: bool = True,
    top_n_nav: int = 8,
    signal_csv: Optional[str] = None,
    sig_col: str = "sig_tier3",
    dir_thr_default: float = 0.10,
) -> Dict[str, Any]:
    if grid is None:
        raise ValueError("grid must be provided")
    g = grid.copy()
    if "dir_thr" not in g.columns:
        g["dir_thr"] = dir_thr_default
    req = ["rsi_n", "L", "S", "tp_ret", "sl_ret", "fee_rate", "dir_thr"]
    if not set(req).issubset(set(g.columns)):
        raise ValueError(f"grid must contain: {', '.join(req)}")
    prod = str(product)
    res = []
    nav_list = []
    for _, row in g.iterrows():
        out = run_rsi_ls_intraday_multi(
            min_df=min_df,
            products=[prod],
            day_start=day_start,
            rsi_n=int(row["rsi_n"]),
            short_k=short_k,
            long_k=long_k,
            L=float(row["L"]),
            S=float(row["S"]),
            t_start=t_start,
            force_exit=force_exit,
            tp_ret=float(row["tp_ret"]),
            sl_ret=float(row["sl_ret"]),
            fee_rate=float(row["fee_rate"]),
            one_trade_per_day=one_trade_per_day,
            force_fill=force_fill,
            signal_csv=signal_csv,
            sig_col=sig_col,
            dir_thr=float(row["dir_thr"]),
        )
        perf = calc_perf_from_daily(out["daily"], prod)
        if perf is None:
            continue
        tr = out["trades"]
        tr_prod = tr[tr["product"] == prod]
        cnt_force = int((tr_prod["exit_reason"] == "FORCE").sum())
        cnt_tp = int((tr_prod["exit_reason"] == "TP").sum())
        cnt_sl = int((tr_prod["exit_reason"] == "SL").sum())
        cnt_all = int(tr_prod.shape[0])
        res.append(
            {
                "rsi_n": int(row["rsi_n"]),
                "L": float(row["L"]),
                "S": float(row["S"]),
                "tp_ret": float(row["tp_ret"]),
                "sl_ret": float(row["sl_ret"]),
                "fee_rate": float(row["fee_rate"]),
                "dir_thr": float(row["dir_thr"]),
                "n_days": perf["n"],
                "ann_ret": perf["ann_ret"],
                "ann_vol": perf["ann_vol"],
                "sharpe": perf["sharpe"],
                "max_dd": perf["max_dd"],
                "win_rate": perf["win_rate"],
                "nav_last": perf["nav_last"],
                "trades": cnt_all,
                "n_force": cnt_force,
                "n_tp": cnt_tp,
                "n_sl": cnt_sl,
            }
        )
        dnav = out["daily"][out["daily"]["product"] == prod][["date_int", "nav"]].copy()
        key = f"n={int(row['rsi_n'])} L={float(row['L']):.0f} S={float(row['S']):.0f} tp={float(row['tp_ret']):.3f} sl={float(row['sl_ret']):.3f} thr={float(row['dir_thr']):.2f} fee={float(row['fee_rate']):.5f}"
        dnav["key"] = key
        nav_list.append(dnav)
    stat = pd.DataFrame(res)
    stat = stat[(stat["sharpe"].notna()) | (stat["ann_ret"].notna())]
    stat = stat.sort_values(["sharpe", "ann_ret"], ascending=[False, False])
    nav_long = pd.concat(nav_list, ignore_index=True) if len(nav_list) else pd.DataFrame(columns=["date_int", "nav", "key"])
    if stat.shape[0] and np.isfinite(stat["sharpe"]).any():
        top_keys = stat[np.isfinite(stat["sharpe"])].head(min(top_n_nav, stat.shape[0]))["key"].tolist()
    else:
        top_keys = []
    nav_top = nav_long[nav_long["key"].isin(top_keys)]
    return {"stat": stat, "nav_top": nav_top}

def plot_nav_top(nav_top_dt: pd.DataFrame, main: str = "Top NAV curves"):
    import matplotlib.pyplot as plt
    nav_top = nav_top_dt.copy()
    if nav_top.shape[0] == 0:
        return
    nav_top["date"] = pd.to_datetime(nav_top["date_int"].astype(str), format="%Y%m%d")
    nav_top = nav_top.sort_values(["key", "date"])
    xlim = (nav_top["date"].min(), nav_top["date"].max())
    ylim = (float(nav_top["nav"].min()), float(nav_top["nav"].max()))
    plt.figure()
    plt.title(main)
    plt.xlabel("Date")
    plt.ylabel("NAV")
    for k in sorted(nav_top["key"].unique()):
        dd = nav_top[nav_top["key"] == k]
        plt.plot(dd["date"], dd["nav"], label=k)
    plt.legend(loc="upper left", fontsize=8)
    plt.show()

def as_leg_daily(out: Dict[str, Any], leg_name: str) -> pd.DataFrame:
    d = out["daily"].copy()
    if "date_int" not in d.columns:
        raise ValueError("daily missing date_int")
    if "pnl" not in d.columns:
        raise ValueError("daily missing pnl")
    d = d[["date_int", "pnl"]].copy()
    d["date_int"] = d["date_int"].astype(int)
    d["pnl"] = pd.to_numeric(d["pnl"], errors="coerce")
    d["leg"] = leg_name
    return d

def combine_legs_equal_weight_active(legs_long: pd.DataFrame, leg_names: Optional[List[str]] = None, leg_start: Optional[Dict[str, int]] = None, nav0: float = 1.0) -> Dict[str, Any]:
    dt = legs_long.copy()
    dt["date_int"] = dt["date_int"].astype(int)
    dt["pnl"] = np.where(np.isfinite(dt["pnl"]), dt["pnl"], 0.0)
    if leg_names is None:
        leg_names = sorted(dt["leg"].unique())
    if leg_start is None:
        leg_start = {lg: -np.inf for lg in leg_names}
        im_legs = [lg for lg in leg_names if lg.startswith("IM_")]
        for lg in im_legs:
            leg_start[lg] = 20230101
    else:
        missing = [lg for lg in leg_names if lg not in leg_start]
        for m in missing:
            leg_start[m] = -np.inf
        leg_start = {lg: leg_start[lg] for lg in leg_names}
    all_dates = np.sort(dt["date_int"].unique())
    grid = pd.MultiIndex.from_product([all_dates, leg_names], names=["date_int", "leg"]).to_frame(index=False)
    dt2 = grid.merge(dt, on=["date_int", "leg"], how="left")
    dt2["pnl"] = dt2["pnl"].fillna(0.0)
    dt2["start_int"] = dt2["leg"].map(leg_start).astype(int)
    dt2["active"] = dt2["date_int"] >= dt2["start_int"]
    dt2.drop(columns=["start_int"], inplace=True)
    comb = dt2[dt2["active"] == True].groupby("date_int", as_index=False)["pnl"].mean()
    comb = comb.sort_values("date_int")
    comb["nav"] = nav0 + comb["pnl"].cumsum()
    dt2 = dt2.sort_values(["leg", "date_int"])
    nav_leg = []
    for lg, g in dt2.groupby("leg"):
        rr = g["pnl"].to_numpy()
        act = g["active"].to_numpy()
        rr2 = rr.copy()
        rr2[~np.isfinite(rr2)] = 0.0
        tmp = nav0 + np.cumsum(rr2)
        out = np.full(g.shape[0], np.nan)
        ok = np.where(act)[0]
        if ok.size > 0:
            out[ok] = tmp[ok]
        nav_leg.append(pd.Series(out, index=g.index))
    dt2["nav_leg"] = pd.concat(nav_leg).sort_index()
    return {"comb": comb, "panel": dt2, "leg_start": leg_start}

def plot_nav_bundle_colored(comb: pd.DataFrame, panel: pd.DataFrame, main: str = "NAV (combined + legs)"):
    import matplotlib.pyplot as plt
    comb2 = comb.copy()
    panel2 = panel.copy()
    comb2["date"] = pd.to_datetime(comb2["date_int"].astype(str), format="%Y%m%d")
    panel2["date"] = pd.to_datetime(panel2["date_int"].astype(str), format="%Y%m%d")
    if "nav_leg" not in panel2.columns:
        raise ValueError("panel must have nav_leg (use combine_legs_equal_weight_active output)")
    y_all = pd.concat([comb2["nav"], panel2["nav_leg"]], ignore_index=True)
    y_all = y_all[y_all.notna()]
    x_all = pd.concat([comb2["date"], panel2["date"]], ignore_index=True)
    x_rng = (x_all.min(), x_all.max())
    y_rng = (float(y_all.min()), float(y_all.max()))
    plt.figure()
    plt.title(main)
    plt.xlabel("Date")
    plt.ylabel("NAV")
    plt.plot(comb2["date"], comb2["nav"], color="#000000", linewidth=2, label="COMB")
    cols = {
        "IC_day": "#1f77b4",
        "IC_tail": "#ff7f0e",
        "IM_day": "#2ca02c",
        "IM_tail": "#d62728",
    }
    legs = sorted(panel2["leg"].unique())
    for lg in legs:
        dd = panel2[panel2["leg"] == lg]
        c = cols.get(lg, None)
        if c is None:
            c = None
        plt.plot(dd["date"], dd["nav_leg"], linewidth=1, label=lg, color=c)
    plt.legend(loc="lower right", fontsize=8)
    plt.show()

def dd_duration_days(nav: pd.Series) -> Optional[int]:
    arr = pd.to_numeric(nav, errors="coerce").to_numpy()
    if np.all(~np.isfinite(arr)):
        return None
    peak = np.maximum.accumulate(arr)
    dd = arr / peak - 1.0
    underwater = np.isfinite(dd) & (dd < 0)
    if not underwater.any():
        return 0
    lengths = []
    cur = 0
    for v in underwater:
        if v:
            cur += 1
        else:
            if cur > 0:
                lengths.append(cur)
            cur = 0
    if cur > 0:
        lengths.append(cur)
    return int(max(lengths))

def calc_basic_metrics(comb: pd.DataFrame, ann: int = 252, rf: float = 0.0) -> pd.DataFrame:
    dt = comb.copy()
    if not {"date_int", "pnl", "nav"}.issubset(set(dt.columns)):
        raise ValueError("comb must contain date_int, pnl, nav")
    dt = dt.sort_values("date_int")
    r = pd.to_numeric(dt["pnl"], errors="coerce").fillna(0.0).to_numpy()
    nav = pd.to_numeric(dt["nav"], errors="coerce").replace({np.inf: np.nan, -np.inf: np.nan}).to_numpy()
    ann_ret = float(np.nanmean(r)) * ann
    ann_vol = float(np.nanstd(r)) * np.sqrt(ann)
    sharpe = (ann_ret - rf) / (ann_vol + EPS)
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1.0
    max_dd = float(np.nanmin(dd))
    return pd.DataFrame({"ann_ret": [ann_ret], "max_dd": [max_dd], "sharpe": [sharpe]})

def calc_yearly_with_all(comb: pd.DataFrame, ann: int = 252, rf: float = 0.0) -> pd.DataFrame:
    dt = comb.copy()
    if not {"date_int", "pnl", "nav"}.issubset(set(dt.columns)):
        raise ValueError("comb must contain date_int, pnl, nav")
    dt["date"] = pd.to_datetime(dt["date_int"].astype(str), format="%Y%m%d")
    dt["year"] = dt["date"].dt.year
    dt = dt.sort_values("date")
    rows = []
    for yr, g in dt.groupby("year"):
        r = pd.to_numeric(g["pnl"], errors="coerce").fillna(0.0).to_numpy()
        nav_y = 1.0 + np.cumsum(r)
        ann_ret = float(np.nanmean(r)) * ann
        ann_vol = float(np.nanstd(r)) * np.sqrt(ann)
        sharpe = (ann_ret - rf) / (ann_vol + EPS)
        peak = np.maximum.accumulate(nav_y)
        dd = nav_y / peak - 1.0
        max_dd = float(np.nanmin(dd))
        mdd_dur = dd_duration_days(pd.Series(nav_y))
        rows.append(
            {
                "year": str(int(yr)),
                "days": int(g.shape[0]),
                "ann_ret": ann_ret,
                "max_dd": max_dd,
                "max_dd_duration_days": mdd_dur,
                "sharpe": sharpe,
            }
        )
    r_all = pd.to_numeric(dt["pnl"], errors="coerce").fillna(0.0).to_numpy()
    nav_all = pd.to_numeric(dt["nav"], errors="coerce").replace({np.inf: np.nan, -np.inf: np.nan}).to_numpy()
    if (not np.isfinite(nav_all)).any():
        nav_all = 1.0 + np.cumsum(r_all)
    ann_ret_all = float(np.nanmean(r_all)) * ann
    ann_vol_all = float(np.nanstd(r_all)) * np.sqrt(ann)
    sharpe_all = (ann_ret_all - rf) / (ann_vol_all + EPS)
    peak_all = np.maximum.accumulate(nav_all)
    dd_all = nav_all / peak_all - 1.0
    max_dd_all = float(np.nanmin(dd_all))
    mdd_dur_all = dd_duration_days(pd.Series(nav_all))
    rows.append(
        {
            "year": "ALL",
            "days": int(dt.shape[0]),
            "ann_ret": ann_ret_all,
            "max_dd": max_dd_all,
            "max_dd_duration_days": mdd_dur_all,
            "sharpe": sharpe_all,
        }
    )
    return pd.DataFrame(rows)

def diag_comb(comb: pd.DataFrame) -> Dict[str, Any]:
    dt = comb.copy().sort_values("date_int")
    r = pd.to_numeric(dt["pnl"], errors="coerce").fillna(0.0).to_numpy()
    nav_in = pd.to_numeric(dt["nav"], errors="coerce").replace({np.inf: np.nan, -np.inf: np.nan}).to_numpy()
    nav_from_r = 1.0 + np.cumsum(r)
    return {
        "n_days": int(dt.shape[0]),
        "pnl_summary": {
            "min": float(np.nanmin(r)),
            "max": float(np.nanmax(r)),
            "mean": float(np.nanmean(r)),
            "std": float(np.nanstd(r)),
        },
        "nav_input_last": float(nav_in[-1]) if nav_in.size else np.nan,
        "nav_from_pnl_last": float(nav_from_r[-1]) if nav_from_r.size else np.nan,
        "diff_last_nav": float((nav_in[-1] - nav_from_r[-1])) if nav_in.size and nav_from_r.size else np.nan,
    }

def main():
    print("Generating synthetic data...")
    # Generate 10 days of minute data
    dates = pd.date_range("2024-01-01", "2024-01-15", freq="1min")
    # Filter for approximate trading hours (09:30 - 15:00)
    # Using indexer_between_time requires a DatetimeIndex
    dates = dates[dates.indexer_between_time("09:30", "15:00")]
    
    n = len(dates)
    np.random.seed(42)
    # Random walk price
    returns = np.random.normal(0, 0.0005, n)
    price = 100.0 * np.exp(np.cumsum(returns))
    
    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "TIMEOFDAY": dates.strftime("%H:%M:%S"),
        "product": "IM",
        "open": price,
        "close": price * (1 + np.random.normal(0, 0.0002, n)),
    })
    
    # Construct High/Low
    df["high"] = df[["open", "close"]].max(axis=1) * (1 + np.abs(np.random.normal(0, 0.0002, n)))
    df["low"] = df[["open", "close"]].min(axis=1) * (1 - np.abs(np.random.normal(0, 0.0002, n)))
    
    # Ensure no NaN
    df.dropna(inplace=True)
    
    print(f"Data shape: {df.shape}")
    print("Columns:", df.columns.tolist())
    
    print("\nRunning RSI Strategy Demo...")
    # Run strategy
    res = run_rsi_ls_intraday_multi(
        min_df=df,
        products=["IM"],
        rsi_n=6,
        short_k=5,
        long_k=15,
        L=40,
        S=60,
        t_start="09:45:00",
        t_end="14:30:00",
        force_exit="14:55:00",
        tp_ret=0.01,
        sl_ret=0.01,
        fee_rate=0.0001,
        one_trade_per_day=True,
        force_fill="open_lastbar"
    )
    
    trades = res["trades"]
    daily = res["daily"]
    
    print(f"\nTotal Trades: {len(trades)}")
    if not trades.empty:
        print("\nFirst 5 Trades:")
        print(trades.head().to_string(index=False))
        print("\nExit Reasons:")
        print(trades["exit_reason"].value_counts())
    
    print(f"\nDaily Stats (First 5 days):")
    if not daily.empty:
        print(daily.head().to_string(index=False))
        
        # Calculate performance
        perf = calc_perf_from_daily(daily, "IM")
        print("\nPerformance Metrics:")
        if perf:
            for k, v in perf.items():
                print(f"  {k}: {v}")
        else:
            print("  Not enough data for performance metrics.")

    # Demo Grid Scan
    print("\nRunning Mini Grid Scan...")
    grid = pd.DataFrame([
        {"rsi_n": 5, "L": 40, "S": 60, "tp_ret": 0.01, "sl_ret": 0.01, "fee_rate": 0.0001, "dir_thr": 0.0},
        {"rsi_n": 10, "L": 45, "S": 55, "tp_ret": 0.015, "sl_ret": 0.015, "fee_rate": 0.0001, "dir_thr": 0.0},
    ])
    
    scan_res = grid_scan_rsi(
        min_df=df,
        product="IM",
        grid=grid,
        short_k=5,
        long_k=15,
        top_n_nav=2
    )
    
    print("\nScan Result Statistics:")
    print(scan_res["stat"].to_string(index=False))
    
    print("\nDemo Completed.")

if __name__ == "__main__":
    main()

