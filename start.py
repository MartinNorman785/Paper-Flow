from google.cloud import documentai_v1 as documentai
import re
from split import crop_question
import os
from flask import current_app
from PyPDF2 import PdfReader, PdfWriter
import io

from app import Question
from extensions import db
from cache import save_blocks, load_blocks
from split import crop_question
from models import Question, QuestionFile


PROJECT_ID = "able-nature-490822-p7"
LOCATION = "us"
PROCESSOR_ID_LAYOUT = "3b12470c236a4584"
PROCESSOR_ID = "2792401a0b659ea1"
FILE_PATH = "/workspaces/PastPaper/2024-hsc-maths-adv-short.pdf"


def process_pdf(file_path):
    client = documentai.DocumentProcessorServiceClient()

    name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)

    with open(file_path, "rb") as f:
        pdf_content = f.read()

    request = documentai.ProcessRequest(
        name=name,
        raw_document=documentai.RawDocument(
            content=pdf_content,
            mime_type="application/pdf"
        )
    )

    result = client.process_document(request=request)
    document = result.document

    return document

def get_text_from_layout(document, layout):
    text = ""
    for segment in layout.text_anchor.text_segments:
        start = int(segment.start_index)
        end = int(segment.end_index)
        text += document.text[start:end]
    return text

def questions_from_coordinates(pdf_path, document, layouts):
    reader = PdfReader(pdf_path)
    questions_data = []

    for q in layouts:
        page_start = q['page_start']
        page_end = q['page_end']
        y_top = q['y_top']
        y_bottom = q['y_bottom']

        writer = PdfWriter()
        for page_index in range(page_start, page_end + 1):
            page = reader.pages[page_index]
            page_copy = page

            mediabox = page.mediabox
            top = float(mediabox.top)
            bottom = float(mediabox.bottom)
            left = float(mediabox.left)
            right = float(mediabox.right)

            # Convert relative y coordinates to absolute
            upper = top * y_top
            lower = top * y_bottom

            page_copy.mediabox.upper_right = (right, upper)
            page_copy.mediabox.lower_left = (left, lower)

            writer.add_page(page_copy)

        pdf_bytes_io = io.BytesIO()
        writer.write(pdf_bytes_io)
        pdf_bytes = pdf_bytes_io.getvalue()

        # Extract text from the layout using your existing function
        text = get_text_from_layout(document, q['layout'])

        questions_data.append({'text': text, 'pdf_bytes': pdf_bytes})

    return questions_data


def get_blocks(document):
    blocks = []

    for page_index, page in enumerate(document.pages):
        for block in page.blocks:
            vertices = block.layout.bounding_poly.normalized_vertices
            y_values = [v.y for v in vertices]
            top = min(y_values)
            bottom = max(y_values)

            text = get_text_from_layout(document, block.layout)

            blocks.append({
                "text": text.strip(),
                "top": top,
                "bottom": bottom,
                "page": page_index
            })
    return blocks


def merge_blocks(blocks, max_gap=0.01):
    """Merge vertically adjacent blocks to reduce tiny splits."""
    merged = []
    current = None

    for block in sorted(blocks, key=lambda b: (b["page"], b["top"])):
        if current is None:
            current = block
        elif block["page"] == current["page"] and block["top"] - current["bottom"] < max_gap:
            current["bottom"] = block["bottom"]
            current["text"] += "\n" + block["text"]
        else:
            merged.append(current)
            current = block

    if current:
        merged.append(current)

    return merged


def is_question_start(text):
    """Detect question start: number at beginning + optional dot/paren."""
    return bool(re.match(r"^\d+[\.\)]?\s", text.strip()))


def extract_question_number(text):
    """Extract the numeric question number at start of text."""
    match = re.match(r"^(\d+)[\.\)]?\s", text.strip())
    if match:
        return int(match.group(1))
    return float('inf')  # fallback if no number found


def split_pdf_by_questions(filename, blocks, paper_id):
    blocks = merge_blocks(blocks)

    # Group blocks by page
    all_blocks = sorted(blocks, key=lambda b: (b["page"], b["top"]))

    detected_questions = []
    questions_text = []

    i = 0
    while i < len(all_blocks):
        block = all_blocks[i]
        if is_question_start(block["text"]):
            start_block = block
            y_top = max(0.0, start_block["top"] - 0.01)
            page_start = start_block["page"]

            # Find end of question
            j = i + 1
            y_bottom = start_block["bottom"]
            page_end = start_block["page"]
            question_text_segments = [start_block["text"]]

            while j < len(all_blocks):
                next_block = all_blocks[j]
                if is_question_start(next_block["text"]):
                    break
                if re.match(r"^D[\.\s]", next_block["text"].strip()):
                    y_bottom = next_block["bottom"]
                    page_end = next_block["page"]
                y_bottom = next_block["bottom"]
                page_end = next_block["page"]

                question_text_segments.append(next_block["text"])
                j += 1

            # Full question text
            questions_text.append("\n".join(question_text_segments))

            # Store question info
            q_number = extract_question_number(start_block["text"])
            detected_questions.append({
                "q_number": q_number,
                "page_start": page_start,
                "y_top": y_top,
                "page_end": page_end,
                "y_bottom": y_bottom
            })

            i = j
        else:
            i += 1

    with current_app.app_context():
        # Crop PDFs in order
        for idx, q in enumerate(detected_questions, start=1):
            output_path = f"{filename[:-4]}_question_{idx}.pdf"
            file = crop_question(filename, q["page_start"], q["y_top"], q["y_bottom"])
            
            # Save question record
            question = Question(paper_id=paper_id, filename=output_path, text=questions_text[idx-1])
            questionfile = QuestionFile(filename=output_path, data=file.read()) 

            db.session.add(question)
            db.session.add(questionfile)

        db.session.commit()
    return detected_questions, questions_text


# --- MAIN ---
if __name__ == "__main__":
    blocks = load_blocks()

    if blocks is None:
        print("Processing PDF through Document AI...")
        document = process_pdf(FILE_PATH)
        blocks = get_blocks(document)
        save_blocks(blocks)
        print(f"Blocks saved to cache: {len(blocks)} blocks")
    else:
        print(f"Loaded {len(blocks)} blocks from cache.")

    split_pdf_by_questions(FILE_PATH, blocks)