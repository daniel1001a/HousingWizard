#!/usr/bin/env python3
"""Cash to close, monthly payment, and the highest price that fits every limit at once.

Two commands:

  scenario    One price, one loan: cash needed at closing and monthly payment
              across several interest rates.
  max-price   The highest price where cash, monthly payment and loan limits all
              hold together, and which limit binds.

Examples:
  python3 cash_to_close.py scenario --price 850000 --down-pct 20 --rates 6.25 6.75 --tax-rate 1.1
  python3 cash_to_close.py scenario --preset nyc --price 1250000 --ltv 75 --tax-monthly 900
  python3 cash_to_close.py max-price --cash 250000 --reserve 30000 --renovation 40000 \\
      --monthly-cap 6500 --rate 6.75 --tax-rate 1.2 --insurance 180

Every default below is an assumption, not a quote. The output labels which
numbers you supplied and which ones the script assumed. Replace assumptions with
the lender's Loan Estimate, the real tax bill and an insurance quote as soon as
you have them.

Presets:
  generic  Any US location. Closing costs default to 3% of price (a rough
           national placeholder). Set --transfer-pct if your state or county
           charges the buyer a transfer tax.
  nyc      New York City, 1-3 family, buyer side. Mansion tax on the full price
           at $1M+ (1% to 3.9% by bracket), mortgage recording tax buyer share
           1.8% under $500k and 1.925% at $500k+ (checked 2026-09; the lender
           usually pays a further 0.25%). Seller customarily pays the city and
           state transfer taxes. Title insurance, attorney and misc are
           assumptions.

Standard library only. Python 3.8+.
"""
import argparse
import json
import sys

NYC_MANSION = [  # (price at or above, rate on the full price)
    (25_000_000, 3.9), (20_000_000, 3.75), (15_000_000, 3.5), (10_000_000, 3.25),
    (5_000_000, 2.25), (3_000_000, 1.5), (2_000_000, 1.25), (1_000_000, 1.0),
]


def pmt(loan, annual_pct, years):
    r = annual_pct / 100 / 12
    n = years * 12
    if loan <= 0:
        return 0.0
    return loan * r / (1 - (1 + r) ** -n) if r else loan / n


def nyc_mansion_rate(price):
    for floor, rate in NYC_MANSION:
        if price >= floor:
            return rate
    return 0.0


def closing_costs(price, loan, a):
    """Return (items, total). Each item is (label, amount, source)."""
    items = []
    supplied = a._supplied
    def src(flag):
        return 'you' if flag in supplied else 'assumed'
    if a.preset == 'nyc':
        rate = nyc_mansion_rate(price)
        items.append(('Mansion tax (%.2f%% of full price)' % rate, price * rate / 100, 'rule, checked 2026-09'))
        mrt = 1.8 if loan < 500_000 else 1.925
        items.append(('Mortgage recording tax, buyer share (%.3f%%)' % mrt, loan * mrt / 100, 'rule, checked 2026-09'))
        items.append(('Title insurance (%.2f%% of price)' % a.title_pct, price * a.title_pct / 100, src('title_pct')))
        items.append(('Attorney', a.attorney, src('attorney')))
        items.append(('Lender, recording, other fees', a.misc, src('misc')))
    else:
        if a.closing_pct is not None:
            items.append(('Closing costs (%.2f%% of price)' % a.closing_pct, price * a.closing_pct / 100, src('closing_pct')))
        else:
            items.append(('Closing costs (3% of price placeholder)', price * 0.03, 'assumed'))
        if a.transfer_pct:
            items.append(('Transfer tax paid by buyer (%.3f%%)' % a.transfer_pct, price * a.transfer_pct / 100, 'you'))
        if a.attorney and 'attorney' in supplied:
            items.append(('Attorney', a.attorney, 'you'))
    return items, sum(x[1] for x in items)


def monthly(price, loan, rate, a):
    pi = pmt(loan, rate, a.years)
    tax = a.tax_monthly if a.tax_monthly is not None else price * a.tax_rate / 100 / 12
    ltv = loan / price * 100 if price else 0
    pmi = loan * a.pmi_rate / 100 / 12 if ltv > 80 else 0.0
    total = pi + tax + a.insurance + a.hoa + pmi
    return {'principal_interest': pi, 'tax': tax, 'insurance': a.insurance, 'hoa': a.hoa, 'pmi': pmi, 'total': total}


def resolve_loan(price, a):
    if a.loan is not None:
        return a.loan
    if a.ltv is not None:
        return price * a.ltv / 100
    return price * (100 - a.down_pct) / 100


def cmd_scenario(a):
    price = a.price
    loan = resolve_loan(price, a)
    items, closing = closing_costs(price, loan, a)
    down = price - loan
    need = down + closing
    rates = a.rates
    out = {
        'preset': a.preset, 'price': price, 'loan': loan, 'ltv_pct': round(loan / price * 100, 2),
        'down_payment': down, 'closing_items': [{'item': i, 'amount': round(v), 'source': s} for i, v, s in items],
        'closing_total': round(closing), 'cash_to_close': round(need),
        'monthly': {str(r): {k: round(v) for k, v in monthly(price, loan, r, a).items()} for r in rates},
    }
    if a.preset == 'nyc':
        out['contract_deposit_10pct'] = round(price * 0.10)
    if a.cash is not None:
        left = a.cash - need - a.reserve - a.renovation
        out['cash_available'] = a.cash
        out['left_after_reserve_and_renovation'] = round(left)
    if a.json:
        print(json.dumps(out, indent=1))
        return
    print('Preset: %s' % a.preset)
    print('Price            $%12s' % f'{price:,.0f}')
    print('Loan             $%12s   LTV %.1f%%%s' % (f'{loan:,.0f}', out['ltv_pct'], '   (over 80%%: PMI assumed at %.2f%%/yr)' % a.pmi_rate if out['ltv_pct'] > 80 else ''))
    print('Down payment     $%12s' % f'{down:,.0f}')
    if 'contract_deposit_10pct' in out:
        print('Contract deposit $%12s   (usually 10%%, paid at signing, counts toward the down payment)' % f'{out["contract_deposit_10pct"]:,}')
    print('Closing costs')
    for i, v, s in items:
        print('  %-44s $%10s   [%s]' % (i, f'{v:,.0f}', s))
    print('  %-44s $%10s' % ('Total', f'{closing:,.0f}'))
    print('Cash to close    $%12s   (down payment + closing; excludes reserve and renovation)' % f'{need:,.0f}')
    if a.cash is not None:
        print('Cash available   $%12s   after reserve $%s and renovation $%s: $%s' % (
            f'{a.cash:,.0f}', f'{a.reserve:,.0f}', f'{a.renovation:,.0f}', f'{out["left_after_reserve_and_renovation"]:,}'))
    tax_note = 'tax $%s/mo [%s]' % (f'{monthly(price, loan, rates[0], a)["tax"]:,.0f}', 'you' if ('tax_monthly' in a._supplied or 'tax_rate' in a._supplied) else 'assumed 1.2%/yr of price')
    ins_note = 'insurance $%s/mo [%s]' % (f'{a.insurance:,.0f}', 'you' if 'insurance' in a._supplied else 'assumed')
    print('\nMonthly payment, %d-year fixed; %s; %s' % (a.years, tax_note, ins_note))
    print('  rate     P&I        PMI      total')
    for r in rates:
        m = monthly(price, loan, r, a)
        print('  %5.2f%%  %9s  %7s  %9s' % (r, f'{m["principal_interest"]:,.0f}', f'{m["pmi"]:,.0f}', f'{m["total"]:,.0f}'))


def feasible_loans(price, a):
    """Loans that satisfy cash, monthly and LTV limits at this price (coarse grid)."""
    max_ltv = min(a.max_ltv, a.loan_cap_ltv) if a.loan_cap_ltv else a.max_ltv
    top = price * max_ltv / 100
    budget = a.cash - a.reserve - a.renovation
    ok = []
    steps = 300
    for i in range(steps + 1):
        loan = top * i / steps
        _, closing = closing_costs(price, loan, a)
        cash_need = price - loan + closing
        pay = monthly(price, loan, a.rate, a)['total']
        if cash_need <= budget and pay <= a.monthly_cap:
            ok.append((loan, cash_need, pay))
    return ok


def which_limit_binds(price, a):
    max_ltv = min(a.max_ltv, a.loan_cap_ltv) if a.loan_cap_ltv else a.max_ltv
    grid = [price * max_ltv / 100 * i / 200 for i in range(201)]
    budget = a.cash - a.reserve - a.renovation
    cash_alone = any(price - L + closing_costs(price, L, a)[1] <= budget for L in grid)
    pay_alone = any(monthly(price, L, a.rate, a)['total'] <= a.monthly_cap for L in grid)
    cap = ' (the %.0f%% loan cap stops you borrowing more)' % max_ltv if a.loan_cap_ltv else ''
    if not cash_alone and pay_alone:
        return 'cash' + cap
    if cash_alone and not pay_alone:
        return 'monthly payment'
    if not cash_alone and not pay_alone:
        return 'cash and monthly payment'
    return 'cash and monthly payment together: a bigger loan eases the cash but raises the payment'


def cmd_max_price(a):
    lo, hi = 0.0, a.cash * 60
    best = None
    for _ in range(60):
        mid = (lo + hi) / 2
        f = feasible_loans(mid, a)
        if f:
            lo, best = mid, (mid, f)
        else:
            hi = mid
    if not best:
        print('No price fits: cash after reserve and renovation is too small, or the monthly cap is below taxes and insurance.')
        sys.exit(1)
    price, f = best
    loans = [x[0] for x in f]
    lo_loan, hi_loan = min(loans), max(loans)
    binding = which_limit_binds(price * 1.005, a)
    roomy = feasible_loans(price * 0.95, a)
    roomy_pct = None
    if roomy:
        p95 = price * 0.95
        roomy_pct = [round((p95 - max(x[0] for x in roomy)) / p95 * 100, 1), round((p95 - min(x[0] for x in roomy)) / p95 * 100, 1)]
    out = {
        'max_price': round(price, -3), 'binding_limit': binding,
        'loan_range': [round(lo_loan, -3), round(hi_loan, -3)],
        'down_payment_pct_range': [round((price - hi_loan) / price * 100, 1), round((price - lo_loan) / price * 100, 1)],
        'rate': a.rate, 'monthly_cap': a.monthly_cap,
        'cash_after_reserve_and_renovation': a.cash - a.reserve - a.renovation,
        'down_payment_pct_range_at_95pct_of_max': roomy_pct,
    }
    if a.json:
        print(json.dumps(out, indent=1))
        return
    print('Highest price that fits every limit: about $%s (preset %s, rate %.2f%%)' % (f'{out["max_price"]:,.0f}', a.preset, a.rate))
    print('Binding limit: %s' % binding)
    print('Loans that work at that price: $%s to $%s (down payment %.1f%% to %.1f%%)' % (
        f'{lo_loan:,.0f}', f'{hi_loan:,.0f}', out['down_payment_pct_range'][0], out['down_payment_pct_range'][1]))
    if roomy_pct:
        print('At 95%% of that price you can choose a down payment from %.1f%% to %.1f%%.' % tuple(roomy_pct))
    print('Cash usable for the purchase: $%s (cash $%s minus reserve $%s minus renovation $%s)' % (
        f'{out["cash_after_reserve_and_renovation"]:,.0f}', f'{a.cash:,.0f}', f'{a.reserve:,.0f}', f'{a.renovation:,.0f}'))
    print('\nThis solves all limits together. Solving them one at a time (down payment first,')
    print('then monthly, then reserve) is how two contradictory answers happen.')
    print('Taxes, insurance and closing costs are assumptions unless you passed them.')


SUPPLIED = set()


class Recorder(argparse.Action):
    """Remember which flags the user actually passed, so output can label assumptions."""
    def __call__(self, parser, ns, values, option_string=None):
        setattr(ns, self.dest, values)
        SUPPLIED.add(self.dest)


def common(p):
    p.add_argument('--preset', choices=['generic', 'nyc'], default='generic')
    p.add_argument('--tax-monthly', type=float, action=Recorder, help='property tax per month, from the real bill')
    p.add_argument('--tax-rate', type=float, default=1.2, action=Recorder, help='annual property tax as %% of price (default 1.2, assumed)')
    p.add_argument('--insurance', type=float, default=200, action=Recorder, help='insurance per month (default 200, assumed)')
    p.add_argument('--hoa', type=float, default=0, action=Recorder)
    p.add_argument('--pmi-rate', type=float, default=0.5, action=Recorder, help='annual PMI %% of loan when LTV > 80 (default 0.5, assumed)')
    p.add_argument('--years', type=int, default=30)
    p.add_argument('--title-pct', type=float, default=0.5, action=Recorder, help='nyc preset: title insurance %% of price (assumed)')
    p.add_argument('--attorney', type=float, default=2000, action=Recorder, help='attorney fee (nyc default 2000, assumed)')
    p.add_argument('--misc', type=float, default=6000, action=Recorder, help='nyc preset: lender, recording and other fees (assumed)')
    p.add_argument('--closing-pct', type=float, action=Recorder, help='generic preset: closing costs as %% of price')
    p.add_argument('--transfer-pct', type=float, default=0, action=Recorder, help='generic preset: transfer tax paid by the buyer, %% of price')
    p.add_argument('--reserve', type=float, default=0, action=Recorder, help='cash kept aside as emergency reserve')
    p.add_argument('--renovation', type=float, default=0, action=Recorder, help='cash needed for work right after closing')
    p.add_argument('--json', action='store_true')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('scenario', help='cash to close and monthly payment for one price')
    s.add_argument('--price', type=float, required=True)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument('--loan', type=float)
    g.add_argument('--ltv', type=float, help='loan as %% of price')
    g.add_argument('--down-pct', type=float, help='down payment as %% of price')
    s.add_argument('--rates', type=float, nargs='+', default=[6.0, 6.5, 7.0, 7.5])
    s.add_argument('--cash', type=float, help='cash available, to show what is left')
    common(s)
    m = sub.add_parser('max-price', help='highest price that fits cash, monthly and loan limits together')
    m.add_argument('--cash', type=float, required=True, help='all cash available for the purchase')
    m.add_argument('--monthly-cap', type=float, required=True, help='the most you will pay per month, all-in')
    m.add_argument('--rate', type=float, required=True)
    m.add_argument('--max-ltv', type=float, default=95, help='lender maximum LTV %% (default 95)')
    m.add_argument('--loan-cap-ltv', type=float, help='a lower LTV cap, e.g. one the seller required')
    common(m)
    SUPPLIED.clear()
    a = ap.parse_args(argv)
    a._supplied = SUPPLIED
    if a.cmd == 'scenario':
        cmd_scenario(a)
    else:
        cmd_max_price(a)


if __name__ == '__main__':
    main()
