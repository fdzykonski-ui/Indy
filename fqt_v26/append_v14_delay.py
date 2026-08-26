#!/usr/bin/env python3
from pathlib import Path

path = Path('user_data/strategies/M4PioneerV26Factory.py')
text = path.read_text(encoding='utf-8')
if 'class M4PioneerValidationV14Delay1' in text:
    raise SystemExit(0)
text += r'''

class M4PioneerValidationV14Delay1(M4PioneerValidationV14):
    """One completed-candle adverse entry delay control; research only."""
    @staticmethod
    def version() -> str:
        return "14.0-delay-plus-1-control"

    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        original = df.get('enter_long', 0).fillna(0).astype(int)
        original_tag = df.get('enter_tag', _fqt_v26_pd.Series(None, index=df.index))
        df['enter_long'] = original.shift(1, fill_value=0).astype(int)
        df['enter_tag'] = original_tag.shift(1)
        return df
'''
path.write_text(text, encoding='utf-8')
