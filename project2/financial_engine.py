"""
financial_engine.py  –  SolarAI Ban Pong
-----------------------------------------
Single source of truth for ALL financial & system calculations.

Architecture:
    predict.py  →  AI production values  →  financial_engine.py  →  Result dict
                                                                       ↓
                                        GIS Panel / Analysis Page / Excel / History

Rules:
    1. Electricity rate is default 4.50 THB/kWh (standard PEA residential rate).
    2. Realistic Solar Modeling:
       - Solar rooftop generation occurs during daytime (08:30 - 16:30).
       - Daytime electricity consumption ratio (DAYTIME_RATIO) is ~65% for active
         households / offices with daytime air-conditioning & appliances.
       - Direct self-consumption saves 100% of grid purchase price (e.g. 4.50 THB/kWh).
       - Surplus generation is exported under PEA Solar Citizen buyback at 2.20 THB/kWh.
    3. Monthly saving never exceeds user's monthly bill; remaining bill is never negative.
    4. Sizing Recommendations:
       - Bill ~1,500 - 3,500 THB  (e.g. 3,000 THB)  → Recommended 3 kW
       - Bill ~3,800 - 7,500 THB  (e.g. 5,000 THB)  → Recommended 5 kW
       - Bill ~7,500 - 13,000 THB (e.g. 10,000 THB) → Recommended 10 kW
       - Bill ~13,000 - 18,000 THB(e.g. 15,000 THB) → Recommended 15 kW
       - Bill >= 18,000 THB       (e.g. 20,000 THB) → Recommended 20 kW
    5. ALL UI outputs (KPIs, monthly charts, monthly tables, environmental values,
       and bill comparison) are harmonized to match the RECOMMENDED system size
       so every number on the page is 100% consistent.
"""

# ── Constants ─────────────────────────────────────────────────────────────────

ELECTRICITY_RATE          = 4.50    # THB / kWh (PEA residential average)
PEA_BUYBACK_RATE          = 2.20    # THB / kWh (PEA Solar Citizen buyback tariff)
DAYTIME_CONSUMPTION_RATIO = 0.65    # 65% of bill consumed during solar daytime hours

DEFAULT_COSTS = {
    3:  95_000,
    5:  150_000,
    10: 250_000,
    15: 350_000,
    20: 440_000,
}

SYSTEM_KWS = [3, 5, 10, 15, 20]

SYSTEM_SUITABILITY = {
    3:  "เหมาะสำหรับค่าไฟ 1,500 – 3,500 บาท/เดือน (แอร์ 1-2 ตัว)",
    5:  "เหมาะสำหรับค่าไฟ 3,800 – 7,500 บาท/เดือน (แอร์ 2-3 ตัว)",
    10: "เหมาะสำหรับค่าไฟ 7,500 – 13,000 บาท/เดือน (แอร์ 4-6 ตัว / บ้านหลังใหญ่)",
    15: "เหมาะสำหรับค่าไฟ 13,000 – 18,000 บาท/เดือน (โฮมออฟฟิศ / สำนักงาน)",
    20: "เหมาะสำหรับค่าไฟ 18,000 – 25,000+ บาท/เดือน (อาคารพาณิชย์ / ธุรกิจขนาดกลาง)",
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_recommended_kw_for_bill(bill: float) -> int:
    """Determine the optimal engineering-recommended solar capacity (kW) for a given monthly bill."""
    if bill < 3800:
        return 3
    elif bill < 7500:
        return 5
    elif bill < 13000:
        return 10
    elif bill < 18000:
        return 15
    else:
        return 20


def calculate_financials(analysis: dict, monthly_bill: float) -> dict:
    """
    Apply financial calculations to a raw AI analysis dict.

    Args:
        analysis     : result from ``predict.analyze_location()``
        monthly_bill : user's current monthly electricity cost (THB / month)

    Returns:
        Enriched analysis dict. All fields are harmonized and overwritten with
        values calculated for the recommended system size.
    """
    bill = max(100.0, float(monthly_bill))
    rate = float(analysis.get('electricity_rate', ELECTRICITY_RATE))

    # ── Per-system calculation ────────────────────────────────────────────────
    enriched_systems = []
    systems_input = analysis.get('systems', [])

    # If incoming systems list does not have all standard KWs, rebuild/ensure complete list
    existing_kws = {int(s['kw']) for s in systems_input}
    ref_annual_kwh = float(analysis.get('annual_kwh', 7440.0))
    # If analysis annual_kwh is at 5 kW baseline
    kwh_per_kw = ref_annual_kwh / 5.0

    target_systems = []
    for kw in SYSTEM_KWS:
        match = next((s for s in systems_input if int(s['kw']) == kw), None)
        if match:
            target_systems.append(match)
        else:
            target_systems.append({
                'kw': kw,
                'annual_kwh': round(kwh_per_kw * kw, 1),
                'cost': DEFAULT_COSTS.get(kw, kw * 24_000),
            })

    # Daytime energy target for household
    monthly_daytime_budget = bill * DAYTIME_CONSUMPTION_RATIO
    monthly_daytime_kwh_need = monthly_daytime_budget / rate if rate > 0 else 0.0

    for s in target_systems:
        kw       = int(s['kw'])
        ann_kwh  = float(s['annual_kwh'])
        cost     = float(s.get('cost', DEFAULT_COSTS.get(kw, kw * 24_000)))

        # Production derived from AI model
        daily_kwh   = ann_kwh / 365.0
        monthly_kwh = ann_kwh / 12.0

        # Self-consumption modeling:
        # 1. Direct consumption during daylight (offsets full grid rate)
        direct_kwh    = min(monthly_kwh, monthly_daytime_kwh_need)
        direct_saving = direct_kwh * rate

        # 2. Surplus energy export (PEA Solar Citizen buyback rate)
        surplus_kwh    = max(0.0, monthly_kwh - monthly_daytime_kwh_need)
        surplus_saving = surplus_kwh * PEA_BUYBACK_RATE

        # 3. Total monthly savings (capped at total monthly bill)
        monthly_save   = min(bill, round(direct_saving + surplus_saving))
        remaining_bill = max(0.0, round(bill - monthly_save))
        annual_save    = round(monthly_save * 12.0)

        # ROI (%) & Payback period (years)
        roi     = round((annual_save / cost) * 100.0, 1) if cost > 0 else 0.0
        payback = round(cost / annual_save, 1) if annual_save > 0 else 99.0

        enriched_systems.append({
            'kw':             kw,
            'annual_kwh':     round(ann_kwh, 1),
            'daily_kwh':      round(daily_kwh, 2),
            'monthly_kwh':    round(monthly_kwh, 1),
            'cost':           int(cost),
            'monthly_value':  round(monthly_kwh * rate),
            'monthly_save':   round(monthly_save),
            'remaining_bill': round(remaining_bill),
            'annual_save':    int(annual_save),
            'roi':            roi,
            'breakeven':      payback,
            'note':           SYSTEM_SUITABILITY.get(kw, ""),
            'recommended':    False,
        })

    # ── Dynamic Best Recommendation Selection ─────────────────────────────────
    # Determine the target recommended size based on engineering solar rooftop guidelines
    target_rec_kw = get_recommended_kw_for_bill(bill)

    # Find the matching system or fallback to highest ROI
    rec = next((s for s in enriched_systems if s['kw'] == target_rec_kw), None)
    if not rec:
        rec = max(enriched_systems, key=lambda s: (s['roi'], -s['breakeven']))

    for s in enriched_systems:
        s['recommended'] = (s['kw'] == rec['kw'])

    scale_factor = rec['kw'] / 5.0   # Relative to 5 kW baseline

    # ── Harmonize monthly breakdown to match RECOMMENDED system ──────────────
    rec_monthly_data = []
    rec_chart_kwh = []
    for m in analysis.get('monthly_data', []):
        m_daily   = round(m['daily_kwh'] * scale_factor, 2)
        m_monthly = round(m['monthly_kwh'] * scale_factor, 1)
        rec_monthly_data.append({
            **m,
            'daily_kwh':   m_daily,
            'monthly_kwh': m_monthly,
        })
        rec_chart_kwh.append(m_monthly)

    # ── Harmonize environmental impact to match RECOMMENDED system ────────────
    co2_kg = round(rec['annual_kwh'] * 0.4985, 1)
    trees  = round(co2_kg / 21.77)

    # ── ROI timeline (0–15 years) for recommended system ─────────────────────
    roi_timeline = [
        {
            'year':            y,
            'cumulative_save': rec['annual_save'] * y,
            'net':             rec['annual_save'] * y - rec['cost'],
        }
        for y in range(16)
    ]

    # ── Bill comparison for recommended system ────────────────────────────────
    annual_bill     = round(bill * 12)
    bill_with_solar = max(0, annual_bill - rec['annual_save'])

    # ── Return 100% harmonized result ─────────────────────────────────────────
    return {
        **analysis,

        # Production — reflect RECOMMENDED system
        'annual_kwh':    rec['annual_kwh'],
        'monthly_avg':   rec['monthly_kwh'],
        'current_daily': rec['daily_kwh'],

        # Financial — reflect RECOMMENDED system
        'monthly_bill':     round(bill),
        'electricity_rate': rate,
        'monthly_save':     rec['monthly_save'],
        'annual_save':      rec['annual_save'],
        'remaining_bill':   rec['remaining_bill'],
        'roi':              rec['roi'],
        'breakeven':        rec['breakeven'],
        'recommendation_note': rec['note'],

        # Harmonized monthly breakdown for charts & tables
        'monthly_data':      rec_monthly_data,
        'chart_monthly_kwh': rec_chart_kwh,

        # Harmonized environmental impact
        'co2_saved_kg': co2_kg,
        'trees_equiv':  trees,

        # Systems table (all 5 tiers, with correct financial values)
        'systems':     enriched_systems,
        'recommended': rec,

        # Bill comparison bars
        'typical_annual_bill': annual_bill,
        'bill_with_solar':     bill_with_solar,

        # ROI chart
        'roi_timeline': roi_timeline,
    }

