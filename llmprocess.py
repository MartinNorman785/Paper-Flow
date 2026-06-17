from groq import Groq # LLM API client
import json # To store and proccess LLM response
import os # To access environment variables

from tags import VALID_TAGS # List of tags corresponding with HSC units

client = Groq(api_key=os.environ.get('GROQ_API_KEY')) # Get API key from enviroment and create API client instance

def process_question_with_llm(text):
    prompt = f"""You are processing an exam question from a school past paper.

Your tasks:
1. Remove any administrative text that is not part of the question itself.
   Examples: "Office Use Only", "Do Not Write Here", "For Examiner Use", "NOT TO SCALE"
   page numbers, candidate boxes, blank lines, headers/footers, labels that appear to come directly from a graph.
2. Return the cleaned question text exactly as written — do not rephrase or summarise.
3. 3. Choose 1-3 tags from ONLY this list: {VALID_TAGS}. Do not invent new tags.
Respond with ONLY valid JSON in this exact format, nothing else:
{{
  "cleaned_text": "...",
  "tags": ["tag1", "tag2"]
}}

Question text:
\"\"\"
{text}
\"\"\"
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant", # Model used
        messages=[{"role": "user", "content": prompt}], # Prompt sent to LLM
        temperature=0.1, # Low temperature for more deterministic output
        response_format={"type": "json_object"}, # Spcifying return type
    )

    raw = response.choices[0].message.content.strip() # Get the raw response text

    result  = json.loads(raw) # Convert to python dict
    
    cleaned = result.get("cleaned_text", text).strip() # Get cleaned text
    tags    = ", ".join(result.get("tags", [])) # Get tags and convert to comma seperated string
    return cleaned, tags

def process_questions_bulk_with_llm(questions):
    if not questions:
        return {}

    # Build a numbered list of questions for the prompt
    questions_block = "\n\n".join(
        f'[{qid}]: """\n{text}\n"""'
        for qid, text in questions
    )

    prompt = f"""You are processing exam questions from a school past paper.

For EACH question below:
1. Remove any administrative text that is not part of the question itself.
   Examples: "Office Use Only", "Do Not Write Here", "For Examiner Use", "NOT TO SCALE",
   page numbers, candidate boxes, blank lines, headers/footers, graph labels.
2. Return the cleaned question text exactly as written — do not rephrase or summarise.
3. Choose 1-3 tags from ONLY this list: {VALID_TAGS}. Do not invent new tags.

Respond with ONLY valid JSON in this exact format, nothing else — a single object where each key is the question ID:
{{
  "QUESTION_ID": {{
    "cleaned_text": "...",
    "tags": ["tag1", "tag2"]
  }},
  ...
}}

Questions:
{questions_block}
"""

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    result = json.loads(raw)

    output = {}
    for qid, _ in questions:
        entry = result.get(str(qid)) or result.get(qid)
        if not entry:
            continue
        cleaned = entry.get("cleaned_text", "").strip()
        tags    = ", ".join(entry.get("tags", []))
        output[qid] = (cleaned, tags)

    return output