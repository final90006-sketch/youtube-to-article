# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import render_html as R


def test_vtp_data_escapes_script_end_tag():
    md = "# 標題\n\n## 章節\n段落 </script><script>alert()</script>"
    body, toc, stats, doc_title = R.md_to_html(md, "")
    page = R.build_page({"type": "document", "title": "標題"}, {"source": "md"},
                        body, toc, stats, "", md, "", doc_title)
    assert "<\\/script><script>alert()" in page
    assert "</script><script>alert()" not in page
