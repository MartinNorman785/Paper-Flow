import fitz
from io import BytesIO
import os

def convert_to_pdf_coords(y_norm, page_height):
    return page_height * (1 - y_norm)

def crop_question(input_path, page_num, y_top, y_bottom):
    """
    Crops a single question from a PDF page using normalized coordinates (0-1).
    Returns bytes of the cropped single-page PDF.
    """
    y_top    = float(y_top)
    y_bottom = float(y_bottom)

    src_doc  = fitz.open(input_path)
    src_page = src_doc[page_num]
    page_h   = src_page.rect.height
    page_w   = src_page.rect.width

    clip = fitz.Rect(0, y_top * page_h, page_w, y_bottom * page_h)

    out_doc = fitz.open()
    out_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
    out_doc[-1].set_cropbox(clip)

    pdf_bytes = out_doc.tobytes()
    out_doc.close()
    src_doc.close()

    return pdf_bytes