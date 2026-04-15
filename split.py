from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject, FloatObject
import os
import pickle

from cache import CACHE_DIR

def convert_to_pdf_coords(y_norm, page_height):
    return page_height * (1 - y_norm)

def crop_question(input_path, page_num, y_top, y_bottom):
    """
    Crops a single question from a PDF page using normalized coordinates (0-1).
    Converts Decimal inputs to float to avoid TypeErrors.
    """

    # Ensure normalized coordinates are floats
    y_top = float(y_top)
    y_bottom = float(y_bottom)

    reader = PdfReader(input_path)
    writer = PdfWriter()

    page = reader.pages[page_num]
    mediabox = page.mediabox
    left, right, top, bottom = float(mediabox.left), float(mediabox.right), float(mediabox.top), float(mediabox.bottom)

    # Convert normalized coordinates (0-1) to PDF coordinates
    crop_top = top - (y_top * (top - bottom))
    crop_bottom = top - (y_bottom * (top - bottom))

    # Ensure bottom < top
    if crop_bottom > crop_top:
        crop_bottom, crop_top = crop_top, crop_bottom

    print((left, crop_bottom, right, crop_top))

    # Set crop box
    page.cropbox = RectangleObject((left, crop_bottom, right, crop_top))

    writer.add_page(page)
    
    output = BytesIO()
    writer.write(output)
    output.seek(0)
    return output.read()