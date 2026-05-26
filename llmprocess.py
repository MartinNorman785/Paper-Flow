from groq import Groq
import os

client = Groq(api_key=os.environ.get('GROQ_API_KEY'))

def process_question_with_llm(text):
    prompt = f"""You are processing an exam question from a school past paper.

Your tasks:
1. Remove any administrative text that is not part of the question itself.
   Examples: "Office Use Only", "Do Not Write Here", "For Examiner Use",
   page numbers, candidate boxes, blank lines, headers/footers.
2. Return the cleaned question text exactly as written — do not rephrase or summarise.
3. Generate 1-5 short topic tags describing the subject matter
   (e.g. "calculus", "trigonometry", "WWI", "organic-chemistry").
   Tags must be lowercase, no spaces, hyphens for multi-word tags.

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
        model="llama-3.2-3b-preview",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},  # forces valid JSON output
    )

    raw = response.choices[0].message.content.strip()

    result  = json.loads(raw)
    cleaned = result.get("cleaned_text", text).strip()
    tags    = ", ".join(result.get("tags", []))
    return cleaned, tags