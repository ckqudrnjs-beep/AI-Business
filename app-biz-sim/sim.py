"""앱 제작 비즈니스 수익성 몬테카를로 시뮬레이션 (단위: 만원, 24개월)
모든 파라미터는 가정치이며 PARAMS에서 조정 가능."""
import numpy as np, json
rng = np.random.default_rng(42)
N, M = 5000, 24

# ---------- A. 외주 개발 에이전시 (3인: 개발2 + 영업/PM1, AI 도구 활용) ----------
def agency(price_med=2500, win_rate=0.20, leads_per_month=8, dev_cost=550, pm_cost=450,
           overhead=250, devs=2, ai_boost=1.4, months_per_proj=2.0, warranty=0.08):
    cap = devs * ai_boost / months_per_proj * 1.0   # 월 동시 처리 가능 프로젝트 수(착수 기준)
    cash, cum, path = 0, [], []
    for m in range(M):
        ramp = min(1, 0.3 + m/8)                      # 초기 리드 램프업
        leads = rng.poisson(leads_per_month*ramp)
        wins = rng.binomial(leads, win_rate)
        wins = min(wins, int(round(cap*months_per_proj)))  # 용량 한계
        rev = sum(rng.lognormal(np.log(price_med), 0.5) for _ in range(wins))
        overrun = rng.lognormal(0, 0.25)               # 범위 초과/지연 비용
        cost = devs*dev_cost + pm_cost + overhead + rev*warranty*overrun*0.5
        cash += rev - cost; cum.append(cash)
    return np.array(cum)

# ---------- B. 자체 앱 포트폴리오 (구독/광고) ----------
def portfolio(apps_per_quarter=2, team_cost=1300, dev_cost_per_app=400, mkt_per_app=300,
              hit_p=0.08, ok_p=0.25):
    cum, cash, live = [], 0, []
    for m in range(M):
        cost = team_cost
        if m % 3 == 0:
            for _ in range(apps_per_quarter):
                u = rng.random()
                tier = 'hit' if u < hit_p else 'ok' if u < hit_p+ok_p else 'flop'
                mrr = {'hit': rng.lognormal(np.log(900), .6),
                       'ok': rng.lognormal(np.log(120), .5),
                       'flop': rng.lognormal(np.log(10), .5)}[tier]
                live.append([m, mrr, 3])                # 출시월, 목표 MRR, 램프개월
                cost += dev_cost_per_app + mkt_per_app
        rev = 0
        for a in live:
            age = m - a[0]
            if age >= 1:
                ramp = min(1, age/6); decay = 0.985**max(0, age-12)
                rev += a[1]*ramp*decay
        rev *= 0.85                                    # 스토어 수수료 15%
        cash += rev - cost - rev*0.1                   # 서버/AI API 10%
        cum.append(cash)
    return np.array(cum)

def summarize(name, f, kw):
    r = np.array([f(**kw) for _ in range(N)])
    end = r[:, -1]; be = [(np.argmax(x > 0)+1 if (x > 0).any() else None) for x in r]
    minc = r.min(axis=1)
    be_ok = [b for b in be if b]
    out = dict(name=name, mean=end.mean(), median=np.median(end), p10=np.percentile(end,10),
               p90=np.percentile(end,90), prob_profit=(end>0).mean(),
               worst_cum_cash_p10=np.percentile(minc,10),   # 필요 운영자금(10%ile 최저점)
               breakeven_median_month=float(np.median(be_ok)) if be_ok else None,
               breakeven_prob=len(be_ok)/N)
    return out

scen = [
 ("A 외주 에이전시(기본)", agency, {}),
 ("A 비관(수주율10%,단가1800)", agency, dict(win_rate=0.10, price_med=1800)),
 ("A 낙관(수주율30%,단가3500,AI x1.8)", agency, dict(win_rate=0.30, price_med=3500, ai_boost=1.8)),
 ("B 자체앱 포트폴리오(기본)", portfolio, {}),
 ("B 앱 많이(분기4개)", portfolio, dict(apps_per_quarter=4, team_cost=1300)),
 ("B 히트율 개선(15%)", portfolio, dict(hit_p=0.15, ok_p=0.30)),
]
res = [summarize(*s) for s in scen]
for r in res:
    print(json.dumps({k:(round(v,1) if isinstance(v,float) else v) for k,v in r.items()}, ensure_ascii=False))
json.dump(res, open("results.json","w"), ensure_ascii=False, indent=1, default=float)
