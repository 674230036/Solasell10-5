"""
app.py  –  SolarAI Ban Pong  |  Flask Application Entry Point
"""

import os
import json
import datetime
from flask import Flask, render_template, request, jsonify, send_file

import predict as pr
import financial_engine as fe
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

BASE_DIR      = os.path.dirname(__file__)
HISTORY_FILE  = os.path.join(BASE_DIR, 'predictions.json')
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')

DEFAULT_SETTINGS = {
    'electricity_rate':      4.50,
    'system_costs':          {'3': 95000, '5': 150000, '10': 250000, '15': 350000, '20': 440000},
    'typical_monthly_usage': 400,
}


# ── File I/O helpers ─────────────────────────────────────────────────────────

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_settings():
    saved = load_json(SETTINGS_FILE, {})
    return {**DEFAULT_SETTINGS, **saved}


def get_history():
    return load_json(HISTORY_FILE, [])


def save_history(history):
    save_json(HISTORY_FILE, history)


# ── Page routes ──────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    return render_template('index.html', active='dashboard')


@app.route('/map')
def gis_map():
    return render_template('map.html', active='map')


@app.route('/analysis/<analysis_id>')
def analysis_detail(analysis_id):
    history = get_history()
    record  = next((r for r in history if str(r.get('id')) == str(analysis_id)), None)
    if record is None:
        return render_template('index.html', active='dashboard'), 404
    return render_template('analysis.html', active='map',
                           data=record,
                           data_json=json.dumps(record, ensure_ascii=False))


@app.route('/history')
def history_page():
    return render_template('history.html', active='history')


@app.route('/report')
def report_page():
    history = get_history()
    return render_template('report.html', active='report',
                           history=list(reversed(history))[:20])


@app.route('/report/document/<analysis_id>')
@app.route('/report/print/<analysis_id>')
def report_document(analysis_id):
    history = get_history()
    record  = next((r for r in history if str(r.get('id')) == str(analysis_id)), None)
    if record is None:
        return render_template('index.html', active='dashboard'), 404
    return render_template('document_report.html',
                           data=record,
                           data_json=json.dumps(record, ensure_ascii=False))


@app.route('/settings')
def settings_page():
    return render_template('settings.html', active='settings',
                           settings=get_settings())


# ── API routes ───────────────────────────────────────────────────────────────

@app.route('/api/boundary')
def api_boundary():
    """Serve the Ban Pong district boundary GeoJSON."""
    path = os.path.join(BASE_DIR, 'static', 'banpong.geojson')
    return send_file(path, mimetype='application/json')


@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    body         = request.get_json(silent=True) or {}
    lat          = float(body.get('lat', 13.8))
    lng          = float(body.get('lng', 99.9))
    address      = body.get('address', f'{lat:.5f}, {lng:.5f}')
    monthly_bill = float(body.get('monthly_bill', 3500))

    cfg   = get_settings()
    costs = {int(k): int(v) for k, v in cfg.get('system_costs', {}).items()}

    try:
        # 1. AI prediction (production values only – model untouched)
        raw = pr.analyze_location(lat, lng, system_costs=costs)

        # 2. Financial engine – single source of truth for all financial calc
        result = fe.calculate_financials(raw, monthly_bill)

        rec_id = int(datetime.datetime.now().timestamp() * 1000)
        record = {'id': rec_id, 'address': address, **result}

        history = get_history()
        history.append(record)
        save_history(history)

        return jsonify({'status': 'ok', **record})
    except Exception as exc:
        app.logger.exception('Analysis error')
        return jsonify({'status': 'error', 'message': str(exc)}), 500


@app.route('/api/analysis/<analysis_id>')
def api_get_analysis(analysis_id):
    history = get_history()
    record  = next((r for r in history if str(r.get('id')) == str(analysis_id)), None)
    if record:
        return jsonify(record)
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/stats')
def api_stats():
    history = get_history()
    if not history:
        return jsonify({'count': 0, 'avg_daily': 0, 'avg_annual': 0,
                        'avg_save': 0, 'avg_roi': 0, 'avg_breakeven': 0})
    n = len(history)

    def avg(key):
        vals = [(r.get(key) or 0) for r in history]
        return round(sum(vals) / n, 2) if n > 0 else 0

    return jsonify({
        'count':         n,
        'avg_daily':     avg('current_daily'),
        'avg_annual':    avg('annual_kwh'),
        'avg_save':      avg('annual_save'),
        'avg_roi':       avg('roi'),
        'avg_breakeven': avg('breakeven'),
    })


@app.route('/api/model-info')
def api_model_info():
    try:
        return jsonify(pr.get_model_info())
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/history', methods=['GET'])
def api_history():
    return jsonify(list(reversed(get_history())))


@app.route('/api/history/<analysis_id>', methods=['DELETE'])
def api_delete(analysis_id):
    history = get_history()
    new     = [r for r in history if str(r.get('id')) != str(analysis_id)]
    if len(new) < len(history):
        save_history(new)
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        body    = request.get_json(silent=True) or {}
        current = get_settings()
        current.update(body)
        save_json(SETTINGS_FILE, current)
        return jsonify({'status': 'ok', **current})
    return jsonify(get_settings())


@app.route('/api/export/excel/<analysis_id>')
def api_export_excel(analysis_id):
    history = get_history()

    # Support 'all' to export all historical records into one workbook
    if analysis_id == 'all':
        return export_all_excel(history)

    record = next((r for r in history if str(r.get('id')) == str(analysis_id)), None)
    if not record:
        return jsonify({'error': 'Not found'}), 404

    try:
        import io
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        from openpyxl.chart import BarChart, Reference

        wb = openpyxl.Workbook()

        # Styles
        font_title = Font(name='Calibri', size=16, bold=True, color='111827')
        font_sub   = Font(name='Calibri', size=11, italic=True, color='4B5563')
        font_hdr   = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        font_bold  = Font(name='Calibri', size=11, bold=True, color='111827')
        font_norm  = Font(name='Calibri', size=11, color='1F2937')

        fill_hdr   = PatternFill(start_color='0D9488', end_color='0D9488', fill_type='solid') # Teal 600
        fill_rec   = PatternFill(start_color='D1FAE5', end_color='D1FAE5', fill_type='solid') # Emerald 100
        fill_zebra = PatternFill(start_color='F8FAFC', end_color='F8FAFC', fill_type='solid')

        thin = Side(border_style='thin', color='CBD5E1')
        border_box = Border(left=thin, right=thin, top=thin, bottom=thin)

        align_left   = Alignment(horizontal='left', vertical='center')
        align_right  = Alignment(horizontal='right', vertical='center')
        align_center = Alignment(horizontal='center', vertical='center')

        # ── Sheet 1: สรุปผล ───────────────────────────────────────────────────
        ws1 = wb.active
        ws1.title = 'สรุปผลการวิเคราะห์'

        ws1['A1'] = 'SolarAI Ban Pong – รายงานการวิเคราะห์พลังงานแสงอาทิตย์'
        ws1['A1'].font = font_title
        ws1['A2'] = f"สถานที่: {record.get('address', '')}  |  วันที่: {record.get('analyzed_date', '')} {record.get('analyzed_time', '')}"
        ws1['A2'].font = font_sub

        summary_rows = [
            ('รายการ',                              'ค่าข้อมูล'),
            ('สถานที่วิเคราะห์',                      record.get('address', '')),
            ('พิกัด GPS',                          f"{record.get('lat', 0)}°N, {record.get('lng', 0)}°E"),
            ('วันที่และเวลาที่วิเคราะห์',             f"{record.get('analyzed_date', '')} {record.get('analyzed_time', '')}"),
            ('ระดับความเหมาะสมของพื้นที่',            f"{record.get('suitability', 0)} / 5 ดาว ({record.get('suitability_label', '')})"),
            ('ความมั่นใจโมเดล AI',                   f"{record.get('confidence', 0)}%"),
            ('ระบบโซลาร์เซลล์ที่แนะนำ',               f"{record.get('recommended', {}).get('kw', 0)} kW"),
            ('ราคาระบบที่แนะนำ (บาท)',              record.get('recommended', {}).get('cost', 0)),
            ('ประมาณการผลิตไฟฟ้า / วัน (kWh)',        record.get('current_daily', 0)),
            ('ประมาณการผลิตไฟฟ้า / ปี (kWh)',         record.get('annual_kwh', 0)),
            ('ประหยัดค่าไฟฟ้า / เดือน (บาท)',          record.get('monthly_save', 0)),
            ('ประหยัดค่าไฟฟ้า / ปี (บาท)',             record.get('annual_save', 0)),
            ('ผลตอบแทนการลงทุนต่อปี (ROI)',           f"{record.get('roi', 0)}%"),
            ('ระยะเวลาคืนทุน (ปี)',                  f"{record.get('breakeven', 0)} ปี"),
            ('ปริมาณ CO₂ ที่ลดได้ / ปี (kg)',          record.get('co2_saved_kg', 0)),
            ('เทียบเท่าการปลูกต้นไม้ (ต้น/ปี)',       record.get('trees_equiv', 0)),
        ]

        start_row = 4
        for r_idx, (k, v) in enumerate(summary_rows, start=start_row):
            cell_k = ws1.cell(row=r_idx, column=1, value=k)
            cell_v = ws1.cell(row=r_idx, column=2, value=v)

            if r_idx == start_row:
                cell_k.font, cell_v.font = font_hdr, font_hdr
                cell_k.fill, cell_v.fill = fill_hdr, fill_hdr
                cell_k.alignment, cell_v.alignment = align_left, align_right
            else:
                cell_k.font = font_bold if 'แนะนำ' in str(k) else font_norm
                cell_v.font = font_bold if 'แนะนำ' in str(k) else font_norm
                cell_k.alignment, cell_v.alignment = align_left, align_right
                if r_idx % 2 == 1:
                    cell_k.fill, cell_v.fill = fill_zebra, fill_zebra

            cell_k.border, cell_v.border = border_box, border_box

        # ── Sheet 2: รายเดือน ──────────────────────────────────────────────────
        ws2 = wb.create_sheet(title='พยากรณ์รายเดือน')
        ws2['A1'] = 'การผลิตไฟฟ้าพยากรณ์รายเดือน (12 เดือน)'
        ws2['A1'].font = font_title

        headers_m = ['เดือน', 'ฤดูกาล', 'ผลิต/วัน (kWh)', 'ผลิต/เดือน (kWh)', 'ประหยัด/เดือน (บาท)']
        for c_idx, h in enumerate(headers_m, start=1):
            cell = ws2.cell(row=3, column=c_idx, value=h)
            cell.font, cell.fill, cell.border = font_hdr, fill_hdr, border_box
            cell.alignment = align_center if c_idx == 2 else (align_left if c_idx == 1 else align_right)

        monthly = record.get('monthly_data', [])
        rate = record.get('electricity_rate', 4.18)
        for r_idx, m in enumerate(monthly, start=4):
            m_kwh = m.get('monthly_kwh', 0)
            row_data = [
                m.get('month_name', ''),
                m.get('season', ''),
                m.get('daily_kwh', 0),
                m_kwh,
                round(min(record.get('monthly_bill', 999999), m_kwh * rate))
            ]
            for c_idx, val in enumerate(row_data, start=1):
                cell = ws2.cell(row=r_idx, column=c_idx, value=val)
                cell.font, cell.border = font_norm, border_box
                cell.alignment = align_center if c_idx == 2 else (align_left if c_idx == 1 else align_right)
                if r_idx % 2 == 1:
                    cell.fill = fill_zebra

        # Total Row
        tot_row = len(monthly) + 4
        tot_kwh = sum(m.get('monthly_kwh', 0) for m in monthly)
        tot_save = record.get('annual_save', 0)
        tot_vals = ['รวมทั้งปี', '-', round(record.get('current_daily', 0), 2), round(tot_kwh, 1), tot_save]
        for c_idx, val in enumerate(tot_vals, start=1):
            cell = ws2.cell(row=tot_row, column=c_idx, value=val)
            cell.font = font_bold
            cell.fill = fill_rec
            cell.border = border_box
            cell.alignment = align_center if c_idx == 2 else (align_left if c_idx == 1 else align_right)

        # ── Add Chart to Sheet 2 ───────────────────────────────────────────────
        chart = BarChart()
        chart.type = "col"
        chart.style = 10
        chart.title = "การผลิตไฟฟ้าพยากรณ์รายเดือน (kWh)"
        chart.y_axis.title = 'kWh'
        chart.x_axis.title = 'เดือน'
        chart.width = 14
        chart.height = 7.5

        data_ref = Reference(ws2, min_col=4, min_row=3, max_row=len(monthly)+3, max_col=4)
        cats_ref = Reference(ws2, min_col=1, min_row=4, max_row=len(monthly)+3)
        
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)
        chart.legend = None  # Hide legend since we only have one series

        ws2.add_chart(chart, "G4")

        # ── Sheet 3: เปรียบเทียบขนาดระบบ ───────────────────────────────────────
        ws3 = wb.create_sheet(title='เปรียบเทียบขนาดระบบ')
        ws3['A1'] = 'เปรียบเทียบขนาดระบบโซลาร์เซลล์ (3, 5, 10, 15, 20 kW)'
        ws3['A1'].font = font_title

        headers_s = ['ขนาดระบบ (kW)', 'ผลิต/ปี (kWh)', 'ราคาติดตั้ง (บาท)', 'ประหยัด/ปี (บาท)', 'ROI (%)', 'คืนทุน (ปี)', 'สถานะ']
        for c_idx, h in enumerate(headers_s, start=1):
            cell = ws3.cell(row=3, column=c_idx, value=h)
            cell.font, cell.fill, cell.border = font_hdr, fill_hdr, border_box
            cell.alignment = align_center if c_idx in (1, 7) else align_right

        systems = record.get('systems', [])
        for r_idx, s in enumerate(systems, start=4):
            is_rec = s.get('recommended', False)
            status_text = '⭐ แนะนำ' if is_rec else 'ทางเลือก'
            row_data = [
                f"{s.get('kw', 0)} kW",
                s.get('annual_kwh', 0),
                s.get('cost', 0),
                s.get('annual_save', 0),
                s.get('roi', 0),
                s.get('breakeven', 0),
                status_text
            ]
            for c_idx, val in enumerate(row_data, start=1):
                cell = ws3.cell(row=r_idx, column=c_idx, value=val)
                cell.font = font_bold if is_rec else font_norm
                cell.border = border_box
                cell.alignment = align_center if c_idx in (1, 7) else align_right
                if is_rec:
                    cell.fill = fill_rec

        # Auto-adjust column widths for all sheets
        for sheet in [ws1, ws2, ws3]:
            for col in sheet.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = get_column_letter(col[0].column)
                sheet.column_dimensions[col_letter].width = max(max_len + 4, 14)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f'SolarAI_Report_{analysis_id}.xlsx'
        resp = send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename,
        )
        resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    except Exception as exc:
        app.logger.exception('Excel export error')
        return jsonify({'error': str(exc)}), 500


def export_all_excel(history):
    """Export summary of all history records into one Excel file."""
    try:
        import io
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'ประวัติการวิเคราะห์ทั้งหมด'

        font_title = Font(name='Calibri', size=16, bold=True, color='111827')
        font_hdr   = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        font_norm  = Font(name='Calibri', size=11, color='1F2937')
        fill_hdr   = PatternFill(start_color='0D9488', end_color='0D9488', fill_type='solid')
        fill_zebra = PatternFill(start_color='F8FAFC', end_color='F8FAFC', fill_type='solid')
        thin       = Side(border_style='thin', color='CBD5E1')
        border_box = Border(left=thin, right=thin, top=thin, bottom=thin)

        ws['A1'] = 'SolarAI Ban Pong – รายงานสรุปการวิเคราะห์ทั้งหมด'
        ws['A1'].font = font_title

        headers = ['ID', 'สถานที่', 'วันที่วิเคราะห์', 'ความเหมาะสม', 'ผลิต/วัน (kWh)', 'ผลิต/ปี (kWh)', 'ประหยัด/ปี (บาท)', 'ROI (%)', 'คืนทุน (ปี)']
        for c_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=3, column=c_idx, value=h)
            cell.font, cell.fill, cell.border = font_hdr, fill_hdr, border_box
            cell.alignment = Alignment(horizontal='center', vertical='center')

        for r_idx, r in enumerate(history, start=4):
            row_data = [
                str(r.get('id', '')),
                r.get('address', ''),
                f"{r.get('analyzed_date', '')} {r.get('analyzed_time', '')}",
                f"{r.get('suitability', 0)}/5 ดาว ({r.get('suitability_label', '')})",
                r.get('current_daily', 0),
                r.get('annual_kwh', 0),
                r.get('annual_save', 0),
                r.get('roi', 0),
                r.get('breakeven', 0)
            ]
            for c_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=r_idx, column=c_idx, value=val)
                cell.font, cell.border = font_norm, border_box
                cell.alignment = Alignment(horizontal='right' if c_idx >= 5 else 'left', vertical='center')
                if r_idx % 2 == 1:
                    cell.fill = fill_zebra

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f'SolarAI_All_Reports_{int(datetime.datetime.now().timestamp())}.xlsx'
        resp = send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename,
        )
        resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    except Exception as exc:
        app.logger.exception('All Excel export error')
        return jsonify({'error': str(exc)}), 500


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
