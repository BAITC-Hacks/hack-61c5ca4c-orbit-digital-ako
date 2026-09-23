"""Local tabular readers and reviewable column proposals. No network access."""
import csv
import re
from pathlib import Path
import pandas as pd

SYNONYMS = {
    'src': 'src from source payer sender debit_account from_account отправитель плательщик счет_отправителя'.split(),
    'dst': 'dst to target payee receiver beneficiary credit_account to_account получатель бенефициар'.split(),
    'amount': 'amount sum sum_kzt value amt total сумма сумма_kzt'.split(),
    'date': 'date dt datetime timestamp operation_date дата дата_операции'.split(),
    'n_tx': 'n_tx count cnt tx_count количество'.split(),
    'depth': 'depth hop level колено хоп'.split(),
    'is_seed': 'is_seed seed flag известный исходный'.split(),
    'id': 'id gid account account_id client_id идентификатор счет'.split(),
}

def key(value):
    return re.sub(r'[\s_\-]+', '', str(value).lower().replace('ё', 'е'))

def read_table(path, sheet=None, limit=None):
    path = Path(path)
    meta = {'format': path.suffix[1:], 'encoding': None, 'sheets': []}
    if path.suffix.lower() == '.csv':
        with path.open('rb') as stream:
            sample = stream.read(65536)
        for encoding in ('utf-8-sig', 'cp1251'):
            try:
                import codecs
                decoded = codecs.getincrementaldecoder(encoding)().decode(sample, final=False)
                break
            except UnicodeDecodeError:
                continue
        try:
            sep = csv.Sniffer().sniff(decoded, delimiters=',;\t|').delimiter
        except csv.Error:
            sep = ';' if ';' in decoded else ','
        meta.update(encoding=encoding, delimiter=sep)
        frame = pd.read_csv(path, encoding=encoding, sep=sep, dtype=str, nrows=limit, keep_default_na=False)
    elif path.suffix.lower() == '.parquet':
        import pyarrow.parquet as pq
        if limit:
            batches = pq.ParquetFile(path).iter_batches(batch_size=limit)
            frame = next(batches).to_pandas()
        else:
            frame = pd.read_parquet(path)
    elif path.suffix.lower() == '.xlsx':
        book = pd.ExcelFile(path, engine='openpyxl')
        meta['sheets'] = book.sheet_names
        frame = pd.read_excel(book, sheet_name=sheet or book.sheet_names[0], dtype=str, nrows=limit, keep_default_na=False)
    else:
        raise ValueError('Поддерживаются CSV, Parquet и XLSX')
    frame.columns = frame.columns.astype(str)
    return frame, meta

def parse_amount(series):
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors='coerce')
    def parse(value):
        s = re.sub(r'[\s\u00a0\u202f]', '', str(value))
        if ',' in s and '.' in s:
            s = s.replace(',', '') if s.rfind('.') > s.rfind(',') else s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '.')
        return s
    return pd.to_numeric(series.map(parse), errors='coerce')

def propose(frame):
    result = {}
    used = set()
    for field, names in SYNONYMS.items():
        column = next((c for c in frame if key(c) in {key(n) for n in names}), None)
        if column is not None:
            result[field] = {'column': column, 'confidence': .99, 'reason': 'name'}
            used.add(column)
    # Type hints cannot reliably distinguish sender from receiver; leave those for review.
    for field in ('amount', 'date'):
        if field in result:
            continue
        for c in frame:
            if c in used:
                continue
            s = frame[c].dropna().astype(str).head(50)
            if not len(s):
                continue
            if field == 'date':
                looks = s.str.contains(r'[-/.:]').mean() > .8
                ratio = pd.to_datetime(s, errors='coerce', format='mixed').notna().mean() if looks else 0
            else:
                ratio = parse_amount(s).notna().mean() if s.str.contains(r'[,.]').any() else 0
            if ratio > .9:
                result[field] = {'column': c, 'confidence': .65, 'reason': 'values'}
                used.add(c)
                break
    kind = 'transactions' if 'src' in result and 'date' in result else 'edges' if 'src' in result else 'nodes' if 'depth' in result or 'is_seed' in result else 'seeds'
    return {'kind': kind, 'fields': result}

def map_table(frame, mapping, dayfirst=False):
    selected = {v: k for k, v in mapping.items() if v}
    if not set(selected).issubset(frame.columns):
        raise ValueError('Выбранная колонка отсутствует в файле')
    result = frame[list(selected)].rename(columns=selected).copy()
    for c in ('src', 'dst', 'id'):
        if c in result:
            result[c] = result[c].astype('string').str.strip().replace('', pd.NA)
    if 'amount' in result:
        result['amount'] = parse_amount(result.amount)
    if 'date' in result:
        result['date'] = pd.to_datetime(result.date, errors='coerce', format='mixed', dayfirst=dayfirst, utc=True).dt.tz_localize(None)
    for c in ('depth', 'n_tx'):
        if c in result:
            result[c] = pd.to_numeric(result[c], errors='coerce')
    return result
