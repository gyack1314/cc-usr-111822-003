"""泊松计数的精确置信区间（卡方分布，纯标准库实现）。"""
import math


def _gamma_q_cf(a, x):
    """正则化上不完全伽马函数 Q(a,x)，连分式展开。"""
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b if b != 0 else 1.0 / tiny
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_p(a, x):
    """正则化下不完全伽马函数 P(a,x)。"""
    if x <= 0:
        return 0.0
    if x < a + 1.0:
        ap = a
        term = 1.0 / a
        total = term
        for _ in range(1000):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-12:
                break
        return total * math.exp(-x + a * math.log(x) - math.lgamma(a))
    return 1.0 - _gamma_q_cf(a, x)


def chi2_ppf(p, df):
    """卡方分布分位数，二分反解。chi2_df 即 2*Gamma(df/2)。"""
    if df <= 0:
        return 0.0
    a = df / 2.0
    lo, hi = 0.0, max(float(df), 1.0)
    while _gamma_p(a, hi / 2.0) < p:
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _gamma_p(a, mid / 2.0) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def poisson_interval(events, exposure, confidence=0.95):
    """单位暴露事件率的精确置信区间（Ulm 1990）。

    返回 (点估计, 下限, 上限)；暴露为 0 时无法估计，返回 None。
    """
    if events < 0 or exposure < 0:
        raise ValueError('事件数与暴露量不能为负')
    if exposure == 0:
        return None
    alpha = 1.0 - confidence
    rate = events / exposure
    lower = 0.5 * chi2_ppf(alpha / 2, 2 * events) / exposure if events else 0.0
    upper = 0.5 * chi2_ppf(1 - alpha / 2, 2 * (events + 1)) / exposure
    return rate, lower, upper
