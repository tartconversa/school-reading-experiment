"""统计原语：仅使用标准库。

包含小型矩阵运算、正态与 t 分布数值、O'Brien-Fleming 形风险消耗、
聚类稳健协方差（CR1）、学校层精确置换检验，以及事前声明的判定规则。
所有函数确定性、无随机数，便于正式结论的复现核对。
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

# ---------------------------------------------------------------- 矩阵


def solve(a, b):
    """高斯-约当消元（部分主元）解 Ax=b，a 为 n×n 可逆矩阵。"""
    n = len(a)
    m = [list(a[i]) + [b[i]] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise ValueError("矩阵奇异，无法求解")
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                if f:
                    for k in range(c, n + 1):
                        m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def inverse(a):
    """高斯-约当求逆，a 为 n×n 可逆矩阵。"""
    n = len(a)
    m = [list(a[i]) + [1.0 if j == i else 0.0 for j in range(n)] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise ValueError("矩阵奇异，无法求逆")
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                if f:
                    for k in range(2 * n):
                        m[r][k] -= f * m[c][k]
    return [[m[i][n + j] / m[i][i] for j in range(n)] for i in range(n)]


def matmul(a, b):
    n, inner, m = len(a), len(b), len(b[0])
    return [[sum(a[i][t] * b[t][j] for t in range(inner)) for j in range(m)] for i in range(n)]


# ---------------------------------------------------------------- 分布数值


def normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_ppf(p):
    if not 0.0 < p < 1.0:
        raise ValueError("p 须在 (0,1) 内")
    lo, hi = -1.0, 1.0
    while normal_cdf(hi) < p:
        hi *= 2.0
    while normal_cdf(lo) > p:
        lo *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if normal_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _betacf(a, b, x):
    """不完全 beta 的连分式（Numerical Recipes 6.4）。"""
    maxit, eps, fpmin = 300, 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def beta_inc(a, b, x):
    """正则化不完全 beta 函数 I_x(a,b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t, df):
    """t 分布累计分布函数，df 为自由度。"""
    if df < 1:
        raise ValueError("自由度至少为 1")
    x = df / (df + t * t)
    ib = beta_inc(df / 2.0, 0.5, x)
    return 1.0 - 0.5 * ib if t >= 0 else 0.5 * ib


def t_ppf(p, df):
    if not 0.0 < p < 1.0:
        raise ValueError("p 须在 (0,1) 内")
    lo, hi = -1.0, 1.0
    while t_cdf(hi, df) < p:
        hi *= 2.0
    while t_cdf(lo, df) > p:
        lo *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------- 风险消耗


def obf_nominal_alphas(alpha, looks):
    """O'Brien-Fleming 形加权的逐次名义风险。

    按等间隔信息比例 t_k = k/K 计算消耗函数
    a*(t) = 2(1 - Phi(z_{1-a/2} / sqrt(t)))，
    每次正式查看的名义风险取消耗增量，增量之和恰为整体预算 alpha。
    该做法等价于 OB 形权重的加权 Bonferroni，对任意相关结构有效（偏保守），
    适用条件与近似性质见 统计方案.md。
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha 须在 (0,1) 内")
    if looks < 1:
        raise ValueError("至少一次正式查看")
    z = normal_ppf(1.0 - alpha / 2.0)

    def spend(t):
        return 2.0 * (1.0 - normal_cdf(z / math.sqrt(t)))

    out, prev = [], 0.0
    for k in range(1, looks + 1):
        cum = spend(k / looks)
        out.append(cum - prev)
        prev = cum
    return out


# ---------------------------------------------------------------- 主估计


@dataclass
class IttResult:
    """按分配（ITT）主估计：ANCOVA + 学校层聚类稳健标准误。"""

    estimate: float
    se: float
    df: int
    n: int
    clusters: int
    beta: tuple

    def interval(self, alpha):
        crit = t_ppf(1.0 - alpha / 2.0, self.df)
        return (self.estimate - crit * self.se, self.estimate + crit * self.se)


def ancova_itt(rows):
    """rows 为 (arm01, baseline, endline, cluster) 四元组序列。

    模型：endline ~ 1 + arm + baseline；方差为学校层 CR1 聚类稳健，
    参考分布为 t(G-1)。完整病例（两端成绩均回收）进入估计。
    """
    rows = list(rows)
    n = len(rows)
    if n < 4:
        raise ValueError("可用观测过少，无法估计")
    X = [[1.0, float(r[0]), float(r[1])] for r in rows]
    y = [float(r[2]) for r in rows]
    k = 3
    xtx = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(k)]
    xtx_inv = inverse(xtx)
    beta = solve(xtx, xty)
    resid = [y[i] - sum(beta[a] * X[i][a] for a in range(k)) for i in range(n)]
    clusters = {}
    for i, r in enumerate(rows):
        clusters.setdefault(r[3], []).append(i)
    g = len(clusters)
    if g < 2:
        raise ValueError("聚类数不足，无法计算聚类稳健方差")
    meat = [[0.0] * k for _ in range(k)]
    for idx in clusters.values():
        s = [sum(X[i][a] * resid[i] for i in idx) for a in range(k)]
        for a in range(k):
            for b in range(k):
                meat[a][b] += s[a] * s[b]
    var = matmul(xtx_inv, matmul(meat, xtx_inv))
    corr = (g / (g - 1.0)) * ((n - 1.0) / (n - k))
    var = [[v * corr for v in row] for row in var]
    return IttResult(
        estimate=beta[1],
        se=math.sqrt(max(var[1][1], 0.0)),
        df=g - 1,
        n=n,
        clusters=g,
        beta=tuple(beta),
    )


def school_gains(rows):
    """各校平均（期末-基线）增益，供置换检验与描述使用。"""
    acc = {}
    for arm, base, end, cluster in rows:
        acc.setdefault(cluster, []).append(end - base)
    return {c: sum(v) / len(v) for c, v in acc.items()}


def permutation_pvalue(gains, arms):
    """学校层精确置换检验（双侧）。

    在校级平均增益上重排分配标签，检验尖锐零假设。分配与地区层混杂时
    无法分层置换，本检验对应“标签可任意交换”的假设，解释见 统计方案.md。
    返回 (p 值, 置换总数, 观测统计量)。
    """
    schools = sorted(gains)
    treated = frozenset(s for s in schools if arms[s] == 1)
    control = frozenset(schools) - treated

    def stat(tset):
        cset = frozenset(schools) - tset
        mt = sum(gains[s] for s in tset) / len(tset)
        mc = sum(gains[s] for s in cset) / len(cset)
        return abs(mt - mc)

    observed = stat(treated)
    total, hits = 0, 0
    for combo in itertools.combinations(schools, len(treated)):
        total += 1
        if stat(frozenset(combo)) >= observed - 1e-12:
            hits += 1
    return hits / total, total, observed


# ---------------------------------------------------------------- 判定规则


MEETS_MCID = "MEETS_MCID"        # 区间下限达到最小有意义改善
BELOW_MCID = "BELOW_MCID"        # 区间上限低于最小有意义改善
INCONCLUSIVE = "INCONCLUSIVE"    # 区间跨过最小有意义改善，证据不足


@dataclass
class Decision:
    code: str
    lo: float
    hi: float
    alpha: float
    mcid: float
    includes_zero: bool
    significant: bool


def decide(estimate, se, df, alpha, mcid):
    """事前声明的三分类判定。

    仅用该次查看的名义风险构造区间，与最小有意义改善比较：
    下限达到 mcid 判“达到”；上限低于 mcid 判“排除达到”；其余判“证据不足”。
    显著性（区间是否含零）只作报告信息，不改变判定口径。
    """
    crit = t_ppf(1.0 - alpha / 2.0, df)
    lo, hi = estimate - crit * se, estimate + crit * se
    if lo >= mcid:
        code = MEETS_MCID
    elif hi < mcid:
        code = BELOW_MCID
    else:
        code = INCONCLUSIVE
    includes_zero = lo <= 0.0 <= hi
    return Decision(
        code=code,
        lo=lo,
        hi=hi,
        alpha=alpha,
        mcid=mcid,
        includes_zero=includes_zero,
        significant=not includes_zero,
    )


def two_proportion_z(x1, n1, x2, n2):
    """两比例差的合并 z 诊断量（仅作失访差异提示，不作正式推断）。"""
    if n1 == 0 or n2 == 0:
        return 0.0
    p = (x1 + x2) / (n1 + n2)
    if p in (0.0, 1.0):
        return 0.0
    se = math.sqrt(p * (1.0 - p) * (1.0 / n1 + 1.0 / n2))
    return ((x1 / n1) - (x2 / n2)) / se
