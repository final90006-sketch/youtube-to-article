# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_formats as E


def test_yaml_str_is_json_string_safe_for_escaped_values():
    s = E._yaml_str('路徑\\子目錄 "引號"\n下一行')
    assert json.loads(s) == "路徑/子目錄 '引號' 下一行"
