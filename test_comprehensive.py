"""
Comprehensive Bug Check for SolarAI Ban Pong
"""
import sys, os
sys.path.insert(0, 'f:/Project2-main')
# Set UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

import json
import app as flask_app
flask_app.app.config['TESTING'] = True
client = flask_app.app.test_client()

errors = []
passed = []

def check(name, condition, detail=''):
    if condition:
        passed.append(name)
        print(f'  [OK] {name}')
    else:
        errors.append(name + (': ' + detail if detail else ''))
        print(f'  [FAIL] {name}' + (': ' + detail if detail else ''))

print('\n=== PAGE ROUTES ===')
for route, name in [('/', 'Dashboard'), ('/map', 'GIS Map'), ('/history', 'History'),
                    ('/report', 'Report'), ('/settings', 'Settings')]:
    r = client.get(route)
    check(name + ' HTTP 200', r.status_code == 200)
    content = r.data.decode('utf-8')
    check(name + ' no Python error', 'Internal Server Error' not in content and 'Traceback' not in content)
    check(name + ' no Jinja error', 'jinja2.exceptions' not in content.lower())

print('\n=== API ENDPOINTS ===')
r = client.get('/api/stats')
check('Stats API', r.status_code == 200)
stats = r.get_json()
check('Stats has count', 'count' in stats)

r = client.get('/api/model-info')
check('Model info API', r.status_code == 200)
model = r.get_json()
check('Model has r2', 'r2' in model)
check('Model has features', 'features' in model and len(model['features']) > 0)

r = client.get('/api/history')
check('History API', r.status_code == 200)
history = r.get_json()
check('History is list', isinstance(history, list))

print('\n=== FINANCIAL CALCULATIONS ===')
test_cases = [
    (1500, 3, 'Bill 1500 -> 3kW'),
    (3000, 3, 'Bill 3000 -> 3kW'),
    (5000, 5, 'Bill 5000 -> 5kW'),
    (10000, 10, 'Bill 10000 -> 10kW'),
    (15000, 15, 'Bill 15000 -> 15kW'),
    (20000, 20, 'Bill 20000 -> 20kW'),
]

created_ids = []
for bill, expected_kw, label in test_cases:
    r = client.post('/api/analyze',
        data=json.dumps({'lat': 13.8264, 'lng': 99.8780, 'monthly_bill': bill, 'address': 'Test ' + str(bill)}),
        content_type='application/json')
    check('Analyze ' + str(bill) + ' HTTP', r.status_code == 200)
    result = r.get_json()
    check('Analyze ' + str(bill) + ' status=ok', result.get('status') == 'ok', str(result.get('message', '')))
    
    if result.get('status') == 'ok':
        created_ids.append(result['id'])
        rec = result.get('recommended', {})
        kw = rec.get('kw')
        check(label + ' correct kW', kw == expected_kw, 'got ' + str(kw) + ' kW instead of ' + str(expected_kw) + ' kW')
        
        monthly_save = result.get('monthly_save', 0)
        remaining = result.get('remaining_bill', 0)
        check('Bill ' + str(bill) + ': savings < bill', monthly_save <= bill, 'save=' + str(monthly_save) + ' > bill=' + str(bill))
        check('Bill ' + str(bill) + ': remaining >= 0', remaining >= 0, 'remaining=' + str(remaining))
        check('Bill ' + str(bill) + ': savings+remaining=bill', abs((monthly_save + remaining) - bill) <= 1, 
              'save=' + str(monthly_save) + ' + rem=' + str(remaining) + ' != bill=' + str(bill))
        check('Bill ' + str(bill) + ': ROI > 0', result.get('roi', 0) > 0, 'roi=' + str(result.get('roi')))
        check('Bill ' + str(bill) + ': breakeven > 0', result.get('breakeven', 0) > 0)
        
        systems = result.get('systems', [])
        check('Bill ' + str(bill) + ': 5 system tiers', len(systems) == 5, 'got ' + str(len(systems)) + ' systems')
        system_kws = [s['kw'] for s in systems]
        check('Bill ' + str(bill) + ': has 3,5,10,15,20 kW', sorted(system_kws) == [3,5,10,15,20])
        
        rec_in_systems = [s for s in systems if s.get('recommended')]
        check('Bill ' + str(bill) + ': exactly 1 recommended', len(rec_in_systems) == 1, str(len(rec_in_systems)) + ' marked')

print('\n=== ANALYSIS PAGE RENDERS ===')
if created_ids:
    aid = created_ids[-1]
    r = client.get('/analysis/' + str(aid))
    check('Analysis detail page HTTP', r.status_code == 200)
    content = r.data.decode('utf-8')
    check('Analysis: no Jinja error', 'jinja2.exceptions' not in content.lower())
    check('Analysis: ROI chart present', 'roi-chart' in content)
    check('Analysis: monthly chart present', 'monthly-chart' in content)
    check('Analysis: system comparison present', 'sys-compare-card' in content)
    check('Analysis: bill comparison present', 'bill-compare' in content)
    check('Analysis: recommendation note present', 'rec-reason-banner' in content)
    # Check analysis page has monthly_data JSON embedded
    check('Analysis: data_json present', 'analysis-data' in content)

print('\n=== EXCEL EXPORT ===')
if created_ids:
    aid = created_ids[0]
    r = client.get('/api/export/excel/' + str(aid))
    check('Excel single export', r.status_code == 200)
    check('Excel content-type', 'spreadsheetml' in r.content_type)
    
    r_all = client.get('/api/export/excel/all')
    check('Excel all export', r_all.status_code == 200)

print('\n=== DELETE HISTORY ===')
if created_ids:
    aid = created_ids[0]
    r = client.delete('/api/history/' + str(aid))
    check('Delete history HTTP', r.status_code == 200)
    check('Delete returns ok', r.get_json().get('status') == 'ok')
    
    r2 = client.get('/api/analysis/' + str(aid))
    check('Deleted record returns 404', r2.status_code == 404)

print('\n=== SETTINGS ===')
r = client.post('/api/settings',
    data=json.dumps({'electricity_rate': 4.50, 'system_costs': {'3':95000,'5':150000,'10':250000,'15':350000,'20':440000}}),
    content_type='application/json')
check('Settings save', r.status_code == 200)
check('Settings save returns ok', r.get_json().get('status') == 'ok')

r2 = client.get('/api/settings')
s = r2.get_json()
check('Settings GET', r2.status_code == 200)
check('Settings rate correct', s.get('electricity_rate') == 4.50)
check('Settings has 5 costs', len(s.get('system_costs', {})) == 5)

print('\n=== SUMMARY ===')
print('Passed: ' + str(len(passed)) + ' / ' + str(len(passed) + len(errors)))
if errors:
    print('\nFailed tests:')
    for e in errors:
        print('  - ' + e)
    sys.exit(1)
else:
    print('ALL TESTS PASSED - No bugs found!')
