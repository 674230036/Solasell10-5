import sys
sys.path.insert(0, 'f:/Project2-main')

import predict, financial_engine as fe

raw = predict.analyze_location(13.8264, 99.8780)
print('=== RAW ANALYSIS ===')
print('annual_kwh:', raw.get('annual_kwh'))
print('systems count:', len(raw.get('systems', [])))
print('system kws:', [s['kw'] for s in raw.get('systems', [])])

print()
print('=== FINANCIAL CALCULATIONS ===')
for bill in [1500, 3000, 5000, 10000, 15000, 20000]:
    r = fe.calculate_financials(raw, bill)
    rec = r['recommended']
    kw = rec['kw']
    ms = rec['monthly_save']
    ans = rec['annual_save']
    roi = rec['roi']
    be = rec['breakeven']
    rb = rec['remaining_bill']
    print(f'Bill {bill}: rec={kw}kW | monthly_save={ms} | annual_save={ans} | roi={roi}% | breakeven={be}y | remaining={rb}')
