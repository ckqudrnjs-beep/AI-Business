"""AI 교육/인사이트 구독 서비스 수익 시뮬레이터 (월 단위, 원화).

모든 입력은 '가정'이며 실측치로 교체해야 합니다. 표준 라이브러리만 사용.
사용: python3 simulation/revenue_sim.py [--runs 5000] [--months 24]
"""
import argparse, random, statistics as st

VAT = 1.10          # 판매가는 부가세 포함 → 순매출 = 가격 / 1.1
PG_FEE = 0.033      # 카드 PG 수수료 가정(3.0~3.5%)

# 시나리오 가정: (최소, 최빈, 최대) 삼각분포로 샘플링
SCEN = {
    "price":        (9900, 14900, 19900),   # 월 구독가(부가세 포함)
    "visitors_m1":  (300, 800, 2000),       # 1개월차 오가닉 방문자
    "visitor_growth": (0.03, 0.10, 0.18),   # 월 방문자 성장률(콘텐츠 복리)
    "signup":       (0.02, 0.04, 0.07),     # 방문→무료가입
    "paid":         (0.02, 0.05, 0.10),     # 무료→유료 전환(가입 후 30일 내)
    "churn":        (0.12, 0.08, 0.05),     # 월 해지율 (min,mode,max 순서 무관하게 처리)
    "llm_cost_user": (800, 1800, 4000),     # 유료 1인당 월 LLM 원가
    "ads_budget":   (0, 300000, 1000000),   # 월 광고비
    "cac_paid":     (40000, 25000, 12000),  # 광고 유료고객 1명 획득비 (불확실성 큼)
}
FIXED = 250_000      # 서버·도구·도메인·메일 등 월 고정비
FREE_LLM = 150       # 무료가입자 1명당 1회성 LLM 원가
ZERO_ADS_CAP = 0     # 광고비 0이면 오가닉만

def tri(t):
    lo, hi = min(t), max(t)
    mode = sorted(t)[1]
    return random.triangular(lo, hi, mode)

P_NO_PMF = 0.35   # 시장이 반응하지 않는 확률(제품-시장 적합성 실패) — 핵심 가정
NO_PMF_KEYS = ("visitors_m1", "visitor_growth", "signup", "paid")

def run_once(months):
    p = {k: tri(v) for k, v in SCEN.items()}
    if random.random() < P_NO_PMF:
        # PMF 실패 체제: 유입·전환 계열 변수를 각 범위의 하위 1/3 안에서 추첨
        for k in NO_PMF_KEYS:
            lo, mid = min(SCEN[k]), sorted(SCEN[k])[1]
            p[k] = random.uniform(lo, lo + (mid - lo) * 0.8)
        p["churn"] = max(p["churn"], 0.10)
    # 광고 규모가 커질수록 CAC 상승(저비용 채널 소진)
    p["cac_paid"] *= 1 + p["ads_budget"] / 1_000_000
    paying, cum_profit, cash_min, rows = 0.0, 0.0, 0.0, []
    vis = p["visitors_m1"]
    breakeven = None
    for m in range(1, months + 1):
        signups = vis * p["signup"]
        new_org = signups * p["paid"]
        new_ads = p["ads_budget"] / p["cac_paid"] if p["ads_budget"] else 0
        paying = paying * (1 - p["churn"]) + new_org + new_ads
        net_price = p["price"] / VAT
        revenue = paying * net_price
        cost = (revenue * PG_FEE + paying * p["llm_cost_user"]
                + signups * FREE_LLM + p["ads_budget"] + FIXED)
        profit = revenue - cost
        cum_profit += profit
        cash_min = min(cash_min, cum_profit)
        if breakeven is None and profit > 0:
            breakeven = m
        rows.append((m, paying, revenue, profit, cum_profit))
        vis *= 1 + p["visitor_growth"]
    return p, rows, breakeven, cash_min

def pct(xs, q):
    xs = sorted(xs); return xs[int(q * (len(xs) - 1))]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5000)
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(); random.seed(a.seed)
    res = [run_once(a.months) for _ in range(a.runs)]
    last = [r[1][-1] for r in res]
    print(f"== 몬테카를로 {a.runs}회, {a.months}개월 (원화, 부가세 제외 순매출 기준) ==")
    for label, idx in (("유료 구독자(명)", 1), ("월 매출", 2), ("월 영업이익", 3), ("누적 손익", 4)):
        v = [x[idx] for x in last]
        print(f"{label:<12} P10={pct(v,.1):>12,.0f}  P50={pct(v,.5):>12,.0f}  P90={pct(v,.9):>12,.0f}")
    be = [r[2] for r in res]
    ok = [b for b in be if b]
    print(f"[가정] PMF 실패 확률 {P_NO_PMF:.0%}, 광고비 증가 시 CAC 상승 반영")
    print(f"월 흑자 도달 확률: {len(ok)/len(res):.0%}, 도달 시 중앙값 {st.median(ok) if ok else '-'}개월")
    print(f"{a.months}개월 누적 손익 흑자 확률: {sum(1 for x in last if x[4]>0)/len(res):.0%}")
    print(f"최대 누적 적자(운영자금 필요) P50={-pct([r[3] for r in res],.5):,.0f}  P90(보수)={-pct([r[3] for r in res],.1):,.0f}")
    # 민감도: 각 가정이 12개월차 월 이익과 갖는 상관(스피어만 근사)
    import math
    prof12 = [r[1][11][3] for r in res]
    def rank(xs):
        o = sorted(range(len(xs)), key=lambda i: xs[i]); r = [0]*len(xs)
        for k, i in enumerate(o): r[i] = k
        return r
    rp = rank(prof12); n = len(rp)
    print("\n== 민감도 (12개월차 월이익과 순위상관, 절댓값 큰 순) ==")
    out = []
    for k in SCEN:
        rk = rank([r[0][k] for r in res])
        mp, mk = (n-1)/2, (n-1)/2
        cov = sum((a_-mp)*(b_-mk) for a_, b_ in zip(rp, rk))
        var = sum((a_-mp)**2 for a_ in rp)
        out.append((k, cov/var))
    for k, c in sorted(out, key=lambda x: -abs(x[1])):
        print(f"  {k:<15}{c:+.2f}")
    # 결정론적 3개 시나리오
    print("\n== 고정 시나리오 (월별 요약, 12/24개월) ==")
    fixed = {
      "비관": dict(price=9900, visitors_m1=300, visitor_growth=.03, signup=.02, paid=.02, churn=.12, llm_cost_user=4000, ads_budget=0, cac_paid=40000),
      "기준": dict(price=14900, visitors_m1=800, visitor_growth=.10, signup=.04, paid=.05, churn=.08, llm_cost_user=1800, ads_budget=300000, cac_paid=25000),
      "낙관": dict(price=19900, visitors_m1=2000, visitor_growth=.18, signup=.07, paid=.10, churn=.05, llm_cost_user=800, ads_budget=1000000, cac_paid=12000),
    }
    for name, p in fixed.items():
        paying=0; vis=p["visitors_m1"]; cum=0; be=None; trough=0; snap={}
        for m in range(1, a.months+1):
            s=vis*p["signup"]; paying=paying*(1-p["churn"])+s*p["paid"]+(p["ads_budget"]/p["cac_paid"] if p["ads_budget"] else 0)
            rev=paying*p["price"]/VAT
            prof=rev-(rev*PG_FEE+paying*p["llm_cost_user"]+s*FREE_LLM+p["ads_budget"]+FIXED)
            cum+=prof; trough=min(trough,cum); be=be or (m if prof>0 else None)
            vis*=1+p["visitor_growth"]
            if m in (12,24): snap[m]=(paying,rev,prof,cum)
        print(f"[{name}] 흑자월={be}, 최대적자={-trough:,.0f}")
        for m,(pa,rv,pf,cm) in snap.items():
            print(f"   {m:>2}개월: 유료 {pa:,.0f}명 / 월매출 {rv:,.0f} / 월이익 {pf:,.0f} / 누적 {cm:,.0f}")

if __name__ == "__main__":
    main()
