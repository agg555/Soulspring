"""M0-6: 元.doc(WPS 生成的 Word .doc)→ 元.md。

无 Word/WPS COM、无 LibreOffice 环境下的替代解:直接解析 OLE 复合文档,
按 .doc 规范走 FIB → 0Table 的 piece table(PLCF),按 piece 的 fc 标志位
区分 UTF-16LE / 8-bit(cp1252) 文本段,拼出全文。
"""
from __future__ import annotations

import os
import sys

import olefile

SRC = r"E:\大项目终极anget\可用\自家家具-桶0\元.doc"
DST = os.path.join(os.path.dirname(__file__), "..", "prompts", "旧系统平移", "元-用户认知画像.md")


def doc_text(path: str) -> str:
    ole = olefile.OleFileIO(path)
    wd = ole.openstream("WordDocument").read()

    # FIB: fcClc/lcbClc 指向 0Table 中的 piece table(Word 97+ 固定偏移)
    fc_clc = int.from_bytes(wd[0x01A2:0x01A6], "little")
    lcb_clc = int.from_bytes(wd[0x01A6:0x01AA], "little")
    table_stream = None
    for name in ("0Table", "1Table"):
        if ole.exists(name):
            table_stream = ole.openstream(name).read()
            # 尝试从该表读 plcf,读不动换下一个
            if lcb_clc and fc_clc + lcb_clc <= len(table_stream):
                plcf = table_stream[fc_clc:fc_clc + lcb_clc]
                if len(plcf) >= 12:
                    break

    pieces: list[str] = []
    if lcb_clc and len(plcf) >= 16:
        n = (lcb_clc - 4) // 12  # (n+1) 个 CP + n 个 PCD(8B)
        cps = [int.from_bytes(plcf[i * 4:i * 4 + 4], "little") for i in range(n + 1)]
        pcd_off = 4 * (n + 1)
        for i in range(n):
            pcd = plcf[pcd_off + i * 8: pcd_off + i * 8 + 8]
            fc = int.from_bytes(pcd[2:6], "little")
            length = cps[i + 1] - cps[i]
            if fc & 0x40000000:  # 8-bit piece(cp1252)
                start = (fc & 0x3FFFFFFF) // 2
                raw = wd[start:start + length]
                pieces.append(raw.decode("cp1252", errors="ignore"))
            else:  # 16-bit UTF-16LE
                start = fc & 0x3FFFFFFF
                raw = wd[start:start + length * 2]
                pieces.append(raw.decode("utf-16-le", errors="ignore"))

    if not pieces:  # 兜底:老格式 fcMin..fcMac 单段
        fc_min = int.from_bytes(wd[0x18:0x1C], "little")
        fc_mac = int.from_bytes(wd[0x1C:0x20], "little")
        pieces.append(wd[fc_min:fc_mac].decode("utf-16-le", errors="ignore"))

    text = "".join(pieces)
    # Word 控制符清洗:分页/分节符→换行,其余控制符剔除
    text = text.replace("\r", "\n").replace("\x0b", "\n").replace("\x07", "\n")
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text) if (re := __import__("re")) else text
    return text.strip()


def main() -> None:
    text = doc_text(SRC)
    if len(text) < 500:
        print(f"[FAIL] 提取字数过少({len(text)}),解析可能有误")
        sys.exit(1)
    header = (
        "# 元 · 用户认知画像(旧系统平移)\n\n"
        "> 由 元.doc(WPS,OLE2/.doc)于 2026-08-30 经 scripts/doc2md.py 解析转为 Markdown;\n"
        "> 原始 .doc 保留在 可用\\自家家具-桶0\\ 不动。\n\n"
    )
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, "w", encoding="utf-8") as f:
        f.write(header + text + "\n")
    print(f"[OK] {len(text)} 字 → {DST}")


if __name__ == "__main__":
    main()
