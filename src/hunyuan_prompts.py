"""
HunyuanOCR prompts -- single source of truth.

Why a dedicated module: these strings were duplicated across
bench_deformed.py and smoke_test_hunyuan.py, so the benchmark and the smoke
test could silently drift apart and no longer measure the same thing.

Why Chinese -- MEASURED, twice, on the same image (page_1 of multipage_test,
HunyuanOCR-1.5 weights, transformers backend, backend="pil"):

    DOCUMENT     (zh, official)  -> 2192 chars, 1 <table>, markdown   CORRECT
    a paraphrase (en, ours)      ->  382 chars, 0 <table>, layout JSON  wrong task
    DOCUMENT_EN  (en, official)  -> 2501 chars, 0 <table>, layout JSON  wrong task

The third line is the important one: the English wording copied VERBATIM from
Tencent's own documentation also fails to select document parsing. So this is
not about paraphrasing -- on this setup, only the Chinese string routes to the
right task.

Plausible reason: the English example in the docs illustrates the vLLM
deployment path and dates from the 1.0 release, while we run the 1.5 weights
through transformers. Task routing evidently differs between those paths. The
documentation is not wrong, it just describes a different context.

Practical rule: keep the Chinese strings, and derive variants by MINIMAL edits
of an official string rather than by rewriting it. And whatever the prompt,
check the output shape -- a wrong task returns well-formed JSON, never an
error.

Note that prompt language does not drive output language: the Chinese
document prompt returns Vietnamese text on Vietnamese invoices.

    DOCUMENT       official prompt, drops headers and footers
    DOCUMENT_FULL  same, WITHOUT that clause
    TABLE          table only, straight to HTML
    SPOTTING       text plus coordinates
    FIELDS         information extraction, returns JSON for named fields
    LAYOUT_BOXES   region types and bounding boxes
    *_EN           English wordings -- do NOT select parsing here, see above
"""

# Official document-parsing prompt. The clause 页眉、页脚部分忽略 means
# "ignore headers and footers" -- and the model obeys it, which is how the
# patient name and invoice date disappeared from invoice 1.
DOCUMENT = ("提取文档图片中正文的所有信息用markdown格式表示，其中页眉、页脚部分忽略，"
            "表格用html格式表达，文档中公式用latex格式表示，按照阅读顺序组织进行解析。")

# Same instruction with the header/footer exclusion removed. This is the one
# to use when the header fields matter -- which they do here, since the
# internship subject names patient identity and dates explicitly.
DOCUMENT_FULL = ("提取文档图片中的所有信息用markdown格式表示，包括页眉和页脚，"
                 "表格用html格式表达，文档中公式用latex格式表示，按照阅读顺序组织进行解析。")

# Table only, emitted directly as HTML -- consumable as-is by table_merge.
TABLE = "把图中的表格解析为 HTML。"

# Text spotting: text plus coordinates. Useful to show a reviewer the exact
# region of a suspicious line rather than the whole page.
SPOTTING = "检测并识别图片中的文字，将文本坐标格式化输出。"


def fields_prompt(keys) -> str:
    """Information-extraction prompt: returns JSON for the requested fields.

    HunyuanOCR has a dedicated task for this, which is a cleaner way of
    getting header fields than parsing them out of free-form markdown.
    """
    listed = ", ".join(f"'{k}'" for k in keys)
    return f"提取图片中的: [{listed}] 的字段内容，并按照JSON格式返回。"


# Header fields named by the internship subject, in Vietnamese as they
# appear on the invoices.
INVOICE_FIELD_KEYS = [
    "Tên bệnh viện",      # hospital name
    "Họ tên",             # patient name
    "Ngày hóa đơn",       # invoice date
    "Bác sỹ kê đơn",      # prescribing doctor
    "Tổng tiền",          # grand total
]

# Official English wording of DOCUMENT, verbatim from the Tencent docs.
# MEASURED as NOT selecting document parsing on our setup (1.5 weights via
# transformers): it returns layout JSON instead. Kept for the record, and
# because it is a usable layout-detection prompt -- see LAYOUT_BOXES.
DOCUMENT_EN = (
    "Extract all information from the main body of the document image "
    "and represent it in markdown format, ignoring headers and footers."
    "Tables should be expressed in HTML format, formulas in the document "
    "should be represented using LaTeX format, and the parsing should be "
    "organized according to the reading order."
)

# DOCUMENT_EN with a single word changed: "ignoring" -> "including". Inherits
# the same problem as DOCUMENT_EN -- kept only for symmetry with the Chinese
# variants; do not use for parsing.
DOCUMENT_FULL_EN = DOCUMENT_EN.replace("ignoring headers and footers",
                                       "including headers and footers")

# Not a document-parsing prompt: this loose paraphrase triggers layout
# analysis instead. Kept because it is, by accident, a working
# layout-detection prompt -- it returns JSON with one bbox and a layout_type
# per region, which the modular models give for free via save_to_img() and
# HunyuanOCR otherwise does not expose:
#     [{"layout_type":"doc_title","bbox":"(340,150),(418,150),..."},
#      {"layout_type":"table","bbox":"(485,208),(880,208),..."}]
LAYOUT_BOXES = ("Parse all the content of this document image into markdown, "
                "including headers and footers. Represent tables in HTML "
                "format. Follow the natural reading order.")


ALL = {
    "document": DOCUMENT,
    "document_full": DOCUMENT_FULL,
    "document_en": DOCUMENT_EN,
    "document_full_en": DOCUMENT_FULL_EN,
    "table": TABLE,
    "spotting": SPOTTING,
    "fields": fields_prompt(INVOICE_FIELD_KEYS),
    "layout_boxes": LAYOUT_BOXES,
}
