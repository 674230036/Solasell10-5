import sys
sys.path.insert(0, 'f:/Project2-main')
import app as flask_app
flask_app.app.config['TESTING'] = True

client = flask_app.app.test_client()

# Test all routes work fine
routes = ['/', '/map', '/history', '/report', '/settings', '/api/stats', '/api/history', '/api/model-info']
for route in routes:
    r = client.get(route)
    print(route + ': ' + str(r.status_code))

# Test API analyze for all bill levels
import json
test_cases = [1500, 3000, 5000, 10000, 15000, 20000]
for bill in test_cases:
    r = client.post('/api/analyze',
        data=json.dumps({'lat': 13.8264, 'lng': 99.8780, 'monthly_bill': bill, 'address': 'Test ' + str(bill)}),
        content_type='application/json')
    result = r.get_json()
    rec = result.get('recommended', {})
    status = result['status']
    kw = rec.get('kw')
    ms = result.get('monthly_save')
    roi = result.get('roi')
    print('Bill ' + str(bill) + ': status=' + status + ', rec=' + str(kw) + 'kW, save=' + str(ms) + '/mo, roi=' + str(roi) + '%')

# Test settings save
settings_r = client.post('/api/settings',
    data=json.dumps({'electricity_rate': 4.50, 'system_costs': {'3':95000,'5':150000,'10':250000,'15':350000,'20':440000}}),
    content_type='application/json')
print('Settings save: ' + str(settings_r.status_code) + ' ' + str(settings_r.get_json().get('status')))

# Test Excel export
r_excel = client.get('/api/export/excel/all')
print('Excel all: ' + str(r_excel.status_code) + ' ' + str(r_excel.content_type))
