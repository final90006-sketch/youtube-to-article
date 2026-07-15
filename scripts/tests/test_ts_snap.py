# scripts/tests/test_ts_snap.py
# 時間碼驗證降級：模型自由生成的假時間碼（對不上真實逐字稿段落）→ 停用跳轉，不誤導點擊。
# 對照 deep-research：citation/時間碼別自由生成、離真實依據太遠就別當可跳連結。
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import render_html as R

YT = "https://youtu.be/abc12345678"
SEGS = [0, 60, 120, 180]   # 真實逐字稿段落起點（秒）


def test_trusted_timestamp_stays_linkable():
    # [1:02]=62s 落在真實段落 60s 的容忍內 → 保持可跳、秒數不動（av 零回歸）
    out = R.make_inline(YT, None, seg_starts=SEGS)("重點在 [1:02] 提到")
    assert 'class="ts"' in out and "t=62s" in out and "ts-flat" not in out


def test_fabricated_timestamp_degraded_to_flat():
    # [1:00:00]=3600s 離所有真實段落都超過容忍 → 疑似模型編造 → 降級不可跳、不生成假跳轉
    out = R.make_inline(YT, None, seg_starts=SEGS)("影片說 [1:00:00] 亂寫")
    assert "ts-flat" in out and "href" not in out and "1:00:00" in out


def test_no_segments_keeps_legacy_behavior():
    # 無逐字稿（document 型）→ 不驗證、照舊生成跳轉（向後相容、av 零回歸）
    out = R.make_inline(YT, None, None)("重點在 [1:02] 提到")
    assert 'class="ts"' in out and "t=62s" in out and "ts-flat" not in out


def test_tolerance_boundary():
    # 邊界：差剛好=容忍(90s)仍可信；剛好超過(91s)降級
    segs = [0]
    within = R.make_inline(YT, None, seg_starts=segs)("[1:30] 說")   # 90s, diff 90 == TOL → 可信
    over = R.make_inline(YT, None, seg_starts=segs)("[1:31] 說")     # 91s, diff 91 > TOL → 降級
    assert "ts-flat" not in within and "t=90s" in within
    assert "ts-flat" in over and "href" not in over
