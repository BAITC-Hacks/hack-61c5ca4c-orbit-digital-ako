"""Escaped standalone dossier, printable with browser PDF output."""
from html import escape
from datetime import datetime, timezone
import json
import math
from .explain import rules_for, explain_row

def render_report(case, nodes, edges, summary, config, requests):
    esc = lambda x: escape(str(x))
    selected = nodes.loc[nodes.index.intersection(case['ids'])]
    rules, _ = rules_for(nodes, config)
    cards = []
    for gid, row in selected.iterrows():
        trace = explain_row(row, rules, config)
        checks = ''.join(f'<li>{esc(t["rule"])}: {"✓" if t["passed"] else "✗"}<pre>{esc(json.dumps(t["checks"], ensure_ascii=False, default=str, indent=2))}</pre></li>' for t in trace['trace'])
        cards.append(f'<section><h2>{esc(gid)} · {esc(row.role)}</h2><p>{esc(row.evidence)}</p><p>Приоритет: {row.priority_score:.4f}</p><details open><summary>Трассировка правил</summary><ol>{checks}</ol></details></section>')
    visible = edges[edges.src.isin(selected.index) & edges.dst.isin(selected.index)].head(200)
    diagram_ids = list(selected.index[:60])
    positions = {gid:(400+300*math.cos(i*2*math.pi/max(1,len(diagram_ids))),180+140*math.sin(i*2*math.pi/max(1,len(diagram_ids)))) for i,gid in enumerate(diagram_ids)}
    lines = ''.join(f'<line x1="{positions[e.src][0]}" y1="{positions[e.src][1]}" x2="{positions[e.dst][0]}" y2="{positions[e.dst][1]}" stroke="#9aaeb7" marker-end="url(#arrow)"/>' for e in visible.itertuples() if e.src in positions and e.dst in positions)
    dots = ''.join(f'<g><circle cx="{x}" cy="{y}" r="6" fill="#087c78"/><text x="{x+8}" y="{y+4}" font-size="9">{esc(gid)}</text></g>' for gid,(x,y) in positions.items())
    diagram = f'<svg viewBox="0 0 850 370" role="img" aria-label="Связи выбранных узлов"><defs><marker id="arrow" viewBox="0 0 10 10" refX="12" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="#9aaeb7"/></marker></defs>{lines}{dots}</svg><p>На схеме {len(diagram_ids)} из {len(selected)} узлов дела; ниже — таблица связей.</p>'
    links = ''.join(f'<tr><td>{esc(e.src)}</td><td>→ {esc(e.dst)}</td><td>{e.amount:,.2f}</td></tr>' for e in visible.itertuples())
    limits = ''.join(f'<li>{esc(c["message"])}</li>' for c in summary['capabilities'])
    req = requests[requests.gid.isin(case['ids'])].to_html(index=False, escape=True)
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{esc(case['name'])}</title><style>body{{font:15px system-ui;max-width:1000px;margin:40px auto;color:#172b3a;padding:20px}}h1,h2{{color:#124f52}}section{{break-inside:avoid;border-top:1px solid #ccd5da;margin-top:24px}}pre{{white-space:pre-wrap;font-size:11px}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #ccd5da;padding:8px;text-align:left}}@media print{{body{{margin:0}}details{{display:block}}}}</style><h1>{esc(case['name'])}</h1><p>Аналитическое досье · {esc(datetime.now(timezone.utc).isoformat())}</p><strong>Рабочие гипотезы для проверки. Не вывод о вине.</strong><p>{esc(case.get('notes',''))}</p><p>Период: {esc(summary['profile']['period_label'])} · Валюта: {esc(summary['currency'])}</p><h2>Связи выбранных узлов</h2>{diagram}<table><tr><th>Отправитель</th><th>Получатель</th><th>Сумма</th></tr>{links}</table>{''.join(cards)}<h2>Запросы данных</h2>{req}<h2>Сценарии</h2><pre>{esc(json.dumps(case.get('scenarios',[]),ensure_ascii=False,indent=2))}</pre><h2>Ограничения</h2><ul>{limits}</ul><h2>Параметры расчёта</h2><pre>{esc(json.dumps(config,ensure_ascii=False,indent=2))}</pre></html>'''
