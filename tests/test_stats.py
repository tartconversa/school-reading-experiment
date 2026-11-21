"""统计原语的数值正确性测试（不依赖业务资料）。"""
import math
import unittest

from readingtrial import stats


class DistributionTests(unittest.TestCase):
    def test_t_cdf_known_points(self):
        self.assertAlmostEqual(stats.t_cdf(0.0, 5), 0.5, places=12)
        self.assertAlmostEqual(stats.t_cdf(1.0, 1), 0.75, places=10)  # Cauchy
        self.assertAlmostEqual(stats.t_cdf(1.959964, 10000), 0.975, places=4)
        self.assertAlmostEqual(stats.t_cdf(2.0, 10) + stats.t_cdf(-2.0, 10), 1.0, places=12)

    def test_t_ppf_inverts_cdf(self):
        for df in (1, 5, 11, 60):
            for p in (0.5, 0.9, 0.975, 0.995):
                self.assertAlmostEqual(stats.t_cdf(stats.t_ppf(p, df), df), p, places=9)

    def test_normal_ppf(self):
        self.assertAlmostEqual(stats.normal_ppf(0.975), 1.959964, places=5)
        self.assertAlmostEqual(stats.normal_cdf(stats.normal_ppf(0.3)), 0.3, places=10)

    def test_beta_inc_edges(self):
        self.assertEqual(stats.beta_inc(2, 3, 0.0), 0.0)
        self.assertEqual(stats.beta_inc(2, 3, 1.0), 1.0)
        self.assertAlmostEqual(stats.beta_inc(1, 1, 0.25), 0.25, places=12)


class SpendingTests(unittest.TestCase):
    def test_increments_sum_to_budget(self):
        for looks in (1, 2, 3, 5):
            alphas = stats.obf_nominal_alphas(0.05, looks)
            self.assertAlmostEqual(sum(alphas), 0.05, places=12)
            self.assertTrue(all(a > 0 for a in alphas))

    def test_obf_shape_front_loaded_caution(self):
        a1, a2 = stats.obf_nominal_alphas(0.05, 2)
        self.assertLess(a1, a2)                 # 早期查看更保守
        self.assertAlmostEqual(a1, 0.0056, places=3)


class MatrixTests(unittest.TestCase):
    def test_solve_and_inverse(self):
        a = [[2.0, 1.0], [1.0, 3.0]]
        b = [1.0, 2.0]
        x = stats.solve(a, b)
        self.assertAlmostEqual(x[0], 0.2, places=12)
        self.assertAlmostEqual(x[1], 0.6, places=12)
        inv = stats.inverse(a)
        ident = stats.matmul(a, inv)
        for i in range(2):
            for j in range(2):
                self.assertAlmostEqual(ident[i][j], 1.0 if i == j else 0.0, places=10)


class IttTests(unittest.TestCase):
    def test_exact_fit_recovers_beta(self):
        rows = []
        for c in range(6):
            arm = c % 2
            for j in range(3):
                base = 40 + 5 * j + c
                end = 2.0 * arm + 0.5 * base + 1.0
                rows.append((arm, base, end, f"S{c}"))
        res = stats.ancova_itt(rows)
        self.assertAlmostEqual(res.estimate, 2.0, places=9)
        self.assertAlmostEqual(res.beta[2], 0.5, places=9)
        self.assertAlmostEqual(res.se, 0.0, places=9)
        self.assertEqual(res.df, 5)

    def test_cluster_se_reflects_intracluster_correlation(self):
        # 每校残差同号且符号在校间与分组交叉平衡：聚类内正相关，
        # 聚类稳健 SE 应明显大于朴素（独立假设）SE
        rows = []
        signs = {0: 1.0, 1: 1.0, 2: -1.0, 3: -1.0, 4: 1.0, 5: 1.0, 6: -1.0, 7: -1.0}
        for c in range(8):
            arm = c % 2
            for j in range(4):
                base = 30 + j
                end = 0.3 * base + signs[c] * 5.0
                rows.append((arm, base, end, f"S{c}"))
        res = stats.ancova_itt(rows)
        # 朴素（独立假设）标准误
        n, k = len(rows), 3
        X = [[1.0, float(r[0]), float(r[1])] for r in rows]
        y = [r[2] for r in rows]
        xtx = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
        xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(k)]
        beta = stats.solve(xtx, xty)
        resid = [y[i] - sum(beta[a] * X[i][a] for a in range(k)) for i in range(n)]
        sigma2 = sum(r * r for r in resid) / (n - k)
        xtx_inv = stats.inverse(xtx)
        naive_se = math.sqrt(sigma2 * xtx_inv[1][1])
        self.assertGreater(res.se, 2 * naive_se)


class PermutationTests(unittest.TestCase):
    def test_exact_count(self):
        gains = {"a": 3.0, "b": 3.0, "c": 0.0, "d": 0.0}
        arms = {"a": 1, "b": 1, "c": 0, "d": 0}
        p, total, stat = stats.permutation_pvalue(gains, arms)
        self.assertEqual(total, 6)
        self.assertAlmostEqual(stat, 3.0)
        self.assertAlmostEqual(p, 2 / 6)


class DecisionTests(unittest.TestCase):
    def test_three_way(self):
        d = stats.decide(5.0, 0.5, 11, 0.05, 3.0)
        self.assertEqual(d.code, stats.MEETS_MCID)
        d = stats.decide(0.5, 0.5, 11, 0.05, 3.0)
        self.assertEqual(d.code, stats.BELOW_MCID)
        self.assertTrue(d.includes_zero)
        d = stats.decide(-5.0, 0.5, 11, 0.05, 3.0)
        self.assertEqual(d.code, stats.BELOW_MCID)
        self.assertFalse(d.includes_zero)
        d = stats.decide(3.5, 2.0, 11, 0.05, 3.0)
        self.assertEqual(d.code, stats.INCONCLUSIVE)

    def test_wider_alpha_narrows_interval(self):
        tight = stats.decide(1.0, 1.0, 11, 0.005, 3.0)
        loose = stats.decide(1.0, 1.0, 11, 0.045, 3.0)
        self.assertGreater(tight.hi - tight.lo, loose.hi - loose.lo)


class DiagnosticTests(unittest.TestCase):
    def test_two_proportion_z(self):
        z = stats.two_proportion_z(50, 100, 50, 100)
        self.assertAlmostEqual(z, 0.0, places=12)
        z = stats.two_proportion_z(80, 100, 50, 100)
        self.assertGreater(z, 1.96)


if __name__ == "__main__":
    unittest.main()
