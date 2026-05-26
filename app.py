from flask import Flask, render_template, current_app, request, redirect, url_for, send_file, send_from_directory, flash, send_from_directory, session, abort
from flask_login import login_user, logout_user, login_required, current_user, LoginManager
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from pypdf import PdfReader, PdfWriter
from sqlalchemy.sql import exists
from sqlalchemy import func
from functools import wraps
from dotenv import load_dotenv
from io import BytesIO
import tempfile
import fitz
import uuid
import os
import re

from models import PastPaper, Question, User, PaperFile, QuestionFile, UserPaper, Class, PaperUsed, QuestionUsed
from llmprocess import process_question_with_llm, process_questions_bulk_with_llm
from split import crop_question
from extensions import db



load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'sqlite:///papers.db'
).replace('postgres://', 'postgresql://')

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 280,         
    'pool_timeout': 20,
    'pool_size': 5,
    'max_overflow': 2,
}

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

os.environ.get('GROQ_API_KEY')

with app.app_context():
    db.create_all()

app.secret_key = os.environ.get('SECRET_KEY', 'db479c933cb9108665c3134693b03c96')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    user = User.query.filter_by(id=int(user_id)).first()
    return user

@app.context_processor
def inject_user():
    return dict(user=current_user)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        remember = True
        username = request.form['username']

        existing_user = User.query.filter_by(username=username).first()

        if existing_user:
            flash('Username already taken. Please choose another.', 'error')
            return redirect(url_for('register'))

        password = generate_password_hash(request.form['password'])
        new_user = User(username=username, password_hash=password)
        db.session.add(new_user)
        db.session.commit()

        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user, remember=remember)
            flash('You have been registered successfully.', 'success')
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'error')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        remember = request.form.get('remember') == 'on'
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user, remember=remember)
            flash('You have been logged in successfully.', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    links = UserPaper.query.filter_by(user_id=current_user.id).all()

    papers = [p for link in links if (p := PastPaper.query.get(link.paper_id)) is not None]
    return render_template('index.html', papers=papers)


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    message = None

    if request.method == 'POST':
        if 'file' not in request.files:
            message = "No file part in request."
        else:
            file = request.files['file']
            if file.filename == '':
                message = "No file selected."
            elif file.filename.endswith('.pdf'):
                original_name = secure_filename(file.filename)

                unique_name = f"{uuid.uuid4().hex}_{original_name}"

                paper = PastPaper(filename=unique_name, owner_id=current_user.id)
                paperfile = PaperFile(filename=unique_name, data=file.read())

                db.session.add(paper)
                db.session.add(paperfile)
                db.session.commit()

                link = UserPaper(
                    user_id=current_user.id,
                    paper_id=paper.id
                )
                db.session.add(link)
                db.session.commit()

                return redirect(url_for('view_paper', paper_id=paper.id))
            else:
                message = "Invalid file type. Only PDFs are allowed."

    return render_template('upload.html', message=message)

@app.route('/paper/<int:paper_id>/split')
@login_required
def split(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    return render_template('split.html', paper=paper)

@app.route('/paper/<int:paper_id>/save_splits', methods=['POST'])
@login_required
def save_splits(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    if paper.owner_id != current_user.id:
        abort(403)

    paper_file = PaperFile.query.get_or_404(paper.filename)
    data = request.get_json()
    questions_data = data.get('questions', [])
    auto_extract = data.get('auto_extract', False)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(paper_file.data)
        tmp_path = tmp.name

    # Free the paper file data from memory immediately after writing to disk
    del paper_file

    try:
        for i, q in enumerate(questions_data):
            writer = PdfWriter()
            reader = PdfReader(tmp_path)  # read fresh each time, don't hold in memory

            for page_num in range(q["start_page"], q["end_page"] + 1):
                if q["start_page"] == q["end_page"]:
                    y_top, y_bottom = q["start_y"], q["end_y"]
                elif page_num == q["start_page"]:
                    y_top, y_bottom = q["start_y"], 1.0
                elif page_num == q["end_page"]:
                    y_top, y_bottom = 0.0, q["end_y"]
                else:
                    y_top, y_bottom = 0.0, 1.0

                cropped_bytes = crop_question(tmp_path, page_num, y_top, y_bottom)
                writer.add_page(PdfReader(BytesIO(cropped_bytes)).pages[0])
                del cropped_bytes  # free immediately

            output = BytesIO()
            writer.write(output)
            pdf_bytes = output.getvalue()
            del writer, output  # free immediately

            extracted_text = f"Question {i + 1}"
            if auto_extract:
                try:
                    import fitz
                    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    text = "\n".join(page.get_text() for page in doc).strip()
                    doc.close()
                    if text:
                        extracted_text = text
                except Exception:
                    pass

            filename = f"{uuid.uuid4().hex}.pdf"
            db.session.add(QuestionFile(filename=filename, data=pdf_bytes))
            db.session.add(Question(text=extracted_text, paper_id=paper.id, filename=filename))
            del pdf_bytes  # free immediately

            # Commit each question individually to avoid one giant transaction
            db.session.commit()

    finally:
        os.unlink(tmp_path)

    return {"success": True, "redirect": url_for('view_paper', paper_id=paper.id)}


@app.route('/explore')
@login_required
def explore():
    q = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'new')
    query = PastPaper.query


    if q:
        query = query.filter(PastPaper.filename.contains(q))

    if sort == 'old':
        query = query.order_by(PastPaper.uploaded_at.asc())
    elif sort == 'name':
        query = query.order_by(PastPaper.filename.asc())
    else:  # default: newest
        query = query.order_by(PastPaper.uploaded_at.desc())

    papers = query.all()
    user_papers = {
        up.paper_id for up in UserPaper.query.filter_by(user_id=current_user.id).all()
    }

    return render_template('explore.html', papers=papers, q=q, sort=sort, user_papers=user_papers)


@app.route('/api/search')
@login_required
def api_search():
    q = request.args.get('q', '').strip().lower()
 
    user_papers = {
        up.paper_id for up in UserPaper.query.filter_by(user_id=current_user.id).all()
    }
 
    if not q:
        papers = PastPaper.query.order_by(PastPaper.id.desc()).limit(30).all()
        return {
            "papers": [
                {
                    "id": p.id,
                    "filename": p.filename,
                    "questions": len(p.questions),
                    "owned": p.id in user_papers,
                    "matches": []
                } for p in papers
            ],
            "questions": []
        }
 
    # ── Paper matches (by filename) ───────────────────────────────────────
    filename_matches = PastPaper.query.filter(
        func.lower(PastPaper.filename).contains(q) |
        func.replace(func.replace(func.lower(PastPaper.filename), "_", " "), "-", " ").contains(q)
    ).all()
 
    paper_results_map = {}
    for paper in filename_matches:
        paper_results_map[paper.id] = {"paper": paper, "matches": []}
 
    # ── Question matches (by text or tags) ────────────────────────────────
    question_matches = Question.query.filter(
        func.lower(Question.text).contains(q) |
        func.lower(func.coalesce(Question.tags, '')).contains(q)
    ).all()
 
    question_results = []
 
    for question in question_matches:
        paper = PastPaper.query.get(question.paper_id)
        if not paper:
            continue
 
        # Also bubble the paper up into paper results
        if paper.id not in paper_results_map:
            paper_results_map[paper.id] = {"paper": paper, "matches": []}
 
        match_type = None
        match_value = None
 
        if question.tags and q in question.tags.lower():
            for tag in question.tags.split(','):
                if q in tag.strip().lower():
                    match_type = "tag"
                    match_value = tag.strip()
                    paper_results_map[paper.id]["matches"].append({"type": "tag", "value": tag.strip()})
                    break
 
        if q in question.text.lower():
            idx = question.text.lower().index(q)
            start = max(0, idx - 30)
            end = min(len(question.text), idx + 30 + len(q))
            snippet = ("…" if start > 0 else "") + question.text[start:end] + ("…" if end < len(question.text) else "")
            if not match_type:
                match_type = "question"
                match_value = snippet
            paper_results_map[paper.id]["matches"].append({"type": "question", "value": snippet})
 
        question_results.append({
            "id": question.id,
            "text": question.text,
            "tags": [t.strip() for t in question.tags.split(',')] if question.tags else [],
            "paper_id": paper.id,
            "paper_name": paper.filename,
            "has_pdf": bool(question.filename),
            "match_type": match_type,
            "match_value": match_value,
        })
 
    # Sort papers: filename matches first, then by id desc
    sorted_papers = sorted(
        paper_results_map.values(),
        key=lambda r: (r["paper"].id not in {p.id for p in filename_matches}, -r["paper"].id)
    )[:30]
 
    return {
        "papers": [
            {
                "id": r["paper"].id,
                "filename": r["paper"].filename,
                "questions": len(r["paper"].questions),
                "owned": r["paper"].id in user_papers,
                "matches": r["matches"][:3]
            }
            for r in sorted_papers
        ],
        "questions": question_results[:30]
    }

@app.route('/add-to-my-files/<int:paper_id>', methods=['POST'])
@login_required
def add_to_my_files(paper_id):
    existing = UserPaper.query.filter_by(
        user_id=current_user.id,
        paper_id=paper_id
    ).first()

    if not existing:
        db.session.add(UserPaper(
            user_id=current_user.id,
            paper_id=paper_id
        ))
        db.session.commit()

    flash("Added to your files!", "success")
    return redirect(url_for('view_paper', paper_id=paper_id))

@app.route('/remove_paper/<int:paper_id>', methods=['POST'])
@login_required
def remove_paper(paper_id):

    link = UserPaper.query.filter_by(
        user_id=current_user.id,
        paper_id=paper_id
    ).first()

    if link:
        db.session.delete(link)
        db.session.commit()
        flash("Removed from your files.", "success")
    else:
        flash("Paper not found in your files.", "error")

    return redirect(request.referrer or url_for('explore'))

@app.route('/question/<int:question_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_question(question_id):
    question = Question.query.get_or_404(question_id)
    paper = PastPaper.query.get_or_404(question.paper_id)
    if paper.owner_id != current_user.id:
        abort(403)
 
    if request.method == 'POST':
        question.text = request.form.get('question_text', '').strip() or question.text
        question.tags = request.form.get('tags', '').strip()
        db.session.commit()
        return redirect(url_for('view_question', question_id=question.id))
 
    return render_template('edit_question.html', question=question)

@app.route('/delete/<int:paper_id>', methods=['POST'])
@login_required
def delete_paper(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    if paper.owner_id != current_user.id:
        abort(403)

    # Clean up class assignments and question class assignments
    PaperUsed.query.filter_by(paper_id=paper_id).delete()
    for q in paper.questions:
        QuestionUsed.query.filter_by(question_id=q.id).delete()

    file = PaperFile.query.get_or_404(paper.filename)
    UserPaper.query.filter_by(paper_id=paper_id).delete()

    db.session.delete(paper)
    db.session.delete(file)
    db.session.commit()

    flash("Past paper deleted successfully.", "success")
    return redirect(url_for('index'))


@app.route('/paper/<int:paper_id>')
@login_required
def view_paper(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    edit_name = request.args.get('edit_name') == '1'
    question_ids = [q.id for q in paper.questions]
 
    return render_template(
        'view_paper.html',
        paper=paper,
        edit_name=edit_name,
        has_paper=user_has_paper(current_user, paper),
        class_status=get_paper_class_status(current_user.id, paper_id),
        question_class_status=get_question_class_status_bulk(current_user.id, question_ids),
    )

@app.route('/paper/<int:paper_id>/update_name', methods=['POST'])
@login_required
def update_paper_name(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    if paper.owner_id != current_user.id:
        abort(403)
    
    file = PaperFile.query.get_or_404(paper.filename)

    new_name = unformat_filename(request.form['filename'])
    new_name = secure_filename(new_name.strip())
    new_name = paper.filename.split('_', 1)[0] + "_" + new_name


    if new_name:
        if not new_name.lower().endswith('.pdf'):
            new_name += '.pdf'

        file.filename = new_name

        # Update DB
        paper.filename = new_name
        db.session.commit()

        flash("Paper name updated successfully.", "success")

    return redirect(url_for('view_paper', paper_id=paper.id))

def unformat_filename(display_name):
    name = display_name.strip().lower()

    # Replace spaces with dashes
    name = re.sub(r'\s+', '-', name)

    # Remove invalid characters
    name = re.sub(r'[^a-z0-9\-]', '', name)

    return name

@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    paper = PaperFile.query.filter_by(filename=filename).first_or_404()
    return send_file(BytesIO(paper.data), mimetype='application/pdf')

@app.route('/upload_questions/<path:filename>')
@login_required
def uploaded_question(filename):
    question = QuestionFile.query.filter_by(filename=filename).first_or_404()
    return send_file(BytesIO(question.data), mimetype='application/pdf')
'''
@app.route('/process/<int:paper_id>', methods=['POST'])
@login_required
def process_paper(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    if paper.owner_id != current_user.id:
        abort(403)
    from start import process_pdf, get_blocks, split_pdf_by_questions
    from cache import load_blocks, save_blocks

    paper = PastPaper.query.get_or_404(paper_id)
    file_path = paper.filename
    paperfile = PaperFile.query.get_or_404(file_path)

    # Load or process blocks
    blocks = load_blocks(paper.filename)
    
    if blocks is None:
        document = process_pdf(paperfile.data)
        blocks = get_blocks(document)
        save_blocks(blocks, paper.filename)

    split_pdf_by_questions(file_path, blocks, paper.id)

    return redirect(url_for('view_paper', paper_id=paper.id))
'''
def format_filename(filename):
    name = str(filename).split('_', 1)[-1]
    name = os.path.splitext(name)[0]
    name = re.sub(r'[-_]+', ' ', name)
    words = name.split()
    formatted = []
    for w in words:
        if w.upper() in ["HSC", "IB", "PDF"]:
            formatted.append(w.upper())
        else:
            formatted.append(w.capitalize())
    return " ".join(formatted)

@app.context_processor
def utility_processor():
    return dict(format_filename=format_filename)

@app.route('/question/<int:question_id>')
@login_required
def view_question(question_id):
    question = Question.query.get(question_id)
    if not question:
        abort(404)
 
    return render_template(
        'view_question.html',
        question=question,
        class_status=get_question_class_status(current_user.id, question_id),
    )

@app.route('/paper/<int:paper_id>/add_question', methods=['GET', 'POST'])
@login_required
def add_question(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    if paper.owner_id != current_user.id:
        abort(403)
 
    if request.method == 'POST':
        uploaded_file = request.files.get('file')
        question_text = request.form.get('question_text', '').strip()
 
        if uploaded_file and uploaded_file.filename.endswith('.pdf'):
            # PDF upload — use filename as placeholder text if none provided
            if not question_text:
                question_text = os.path.splitext(
                    secure_filename(uploaded_file.filename)
                )[0].replace('_', ' ').replace('-', ' ')
 
            filename = f"{uuid.uuid4().hex}.pdf"
            qfile = QuestionFile(filename=filename, data=uploaded_file.read())
            question = Question(text=question_text, paper_id=paper.id, filename=filename)
 
            db.session.add(qfile)
            db.session.add(question)
            db.session.commit()
 
            flash("Question added successfully!", "success")
            return redirect(url_for('view_paper', paper_id=paper_id))
 
        # Text-only question
        if not question_text:
            flash("Question text cannot be empty.", "error")
            return redirect(url_for('add_question', paper_id=paper_id))
 
        db.session.add(Question(text=question_text, paper_id=paper.id))
        db.session.commit()
 
        flash("Question added successfully!", "success")
        return redirect(url_for('view_paper', paper_id=paper_id))
 
    return render_template('add_question.html', paper=paper)

@app.route('/delete_question/<int:question_id>', methods=['POST'])
@login_required
def delete_question(question_id):
    question = Question.query.get_or_404(question_id)
    paper = PastPaper.query.get_or_404(question.paper_id)
    if paper.owner_id != current_user.id:
        abort(403)

    QuestionUsed.query.filter_by(question_id=question_id).delete()

    if question.filename is not None:
        file = QuestionFile.query.get_or_404(question.filename)
        db.session.delete(file)

    db.session.delete(question)
    db.session.commit()

    flash("Deleted", "success")
    return redirect(url_for('view_paper', paper_id=question.paper_id))


@app.route('/delete_questions/<int:paper_id>', methods=['POST'])
@login_required
def delete_questions(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    if paper.owner_id != current_user.id:
        abort(403)

    for q in paper.questions:
        QuestionUsed.query.filter_by(question_id=q.id).delete()
        if q.filename:
            db.session.delete(QuestionFile.query.get_or_404(q.filename))
        db.session.delete(q)

    db.session.commit()
    flash("All questions deleted.", "success")
    return redirect(url_for('view_paper', paper_id=paper_id))

def user_has_paper(user, paper):
    return db.session.query(
        exists().where(
            UserPaper.user_id == user.id,
            UserPaper.paper_id == paper.id
        )
    ).scalar()


@app.route('/classes')
@login_required
def view_classes():
    user_classes = (
        Class.query
        .filter_by(user_id=current_user.id)
        .order_by(Class.name)
        .all()
    )
 
    # { class_id -> [{"paper": PastPaper, "flagged": bool}, ...] }
    class_papers = {}
    for cls in user_classes:
        papers = []
        for state in cls.paper_states:
            paper = PastPaper.query.get(state.paper_id)
            if paper:
                papers.append({"paper": paper, "flagged": state.flagged})
        class_papers[cls.id] = papers
 
    return render_template(
        'classes.html',
        user_classes=user_classes,
        class_papers=class_papers,
    )
 
 
@app.route('/classes/<int:class_id>')
@login_required
def view_class(class_id):
    cls = Class.query.filter_by(id=class_id, user_id=current_user.id).first_or_404()
 
    # ── Papers ─────────────────────────────────────────────────────────────
    # All papers in the user's files (owned or added)
    user_paper_ids = {
        up.paper_id for up in UserPaper.query.filter_by(user_id=current_user.id).all()
    }
    all_papers = (
        PastPaper.query
        .filter(PastPaper.id.in_(user_paper_ids))
        .order_by(PastPaper.uploaded_at.desc())
        .all()
    )
 
    assigned_paper_ids = {s.paper_id for s in cls.paper_states}
    assigned_papers   = [{"paper": p} for p in all_papers if p.id in assigned_paper_ids]
    unassigned_papers = [p for p in all_papers if p.id not in assigned_paper_ids]
 
    # ── Questions ──────────────────────────────────────────────────────────
    # All questions from any paper in the user's files (owned or added)
    all_questions = (
        Question.query
        .filter(Question.paper_id.in_(user_paper_ids))
        .order_by(Question.id.desc())
        .all()
    )
 
    assigned_question_ids = {s.question_id for s in cls.question_states}
    assigned_questions   = [{"question": q} for q in all_questions if q.id in assigned_question_ids]
    unassigned_questions = [q for q in all_questions if q.id not in assigned_question_ids]
 
    per_page_papers    = int(request.args.get('pp_papers',    10))
    per_page_questions = int(request.args.get('pp_questions', 10))
 
    return render_template(
        'class.html',
        cls=cls,
        assigned_papers=assigned_papers,
        unassigned_papers=unassigned_papers,
        assigned_questions=assigned_questions,
        unassigned_questions=unassigned_questions,
        per_page_papers=per_page_papers,
        per_page_questions=per_page_questions,
    )
 
 
@app.route('/classes/new', methods=['GET', 'POST'])
@login_required
def new_class():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Class name cannot be empty.', 'error')
            return redirect(url_for('new_class'))
        db.session.add(Class(user_id=current_user.id, name=name))
        db.session.commit()
        flash(f'Class "{name}" created.', 'success')
        return redirect(url_for('view_classes'))
    return render_template('new_class.html')
 
 
@app.route('/classes/<int:class_id>/delete', methods=['POST'])
@login_required
def delete_class(class_id):
    cls = Class.query.filter_by(id=class_id, user_id=current_user.id).first_or_404()
    db.session.delete(cls)
    db.session.commit()
    flash(f'Class "{cls.name}" deleted.', 'success')
    return redirect(url_for('view_classes'))

def get_paper_class_status(user_id, paper_id):
    """One dict per class the user owns: was this paper assigned to it?"""
    user_classes = Class.query.filter_by(user_id=user_id).order_by(Class.name).all()
    assigned_ids = {
        s.class_id for s in PaperUsed.query.filter_by(paper_id=paper_id).all()
    }
    return [
        {"class_id": cls.id, "class_name": cls.name, "assigned": cls.id in assigned_ids}
        for cls in user_classes
    ]
 
 
def get_question_class_status(user_id, question_id):
    """One dict per class the user owns: was this question assigned to it?"""
    user_classes = Class.query.filter_by(user_id=user_id).order_by(Class.name).all()
    assigned_ids = {
        s.class_id for s in QuestionUsed.query.filter_by(question_id=question_id).all()
    }
    return [
        {"class_id": cls.id, "class_name": cls.name, "assigned": cls.id in assigned_ids}
        for cls in user_classes
    ]
 
 
def get_question_class_status_bulk(user_id, question_ids):
    """
    Bulk version — 2 DB queries total regardless of question count.
    Returns { question_id: [{"class_id": ..., "class_name": ..., "assigned": ...}, ...] }
    """
    user_classes = Class.query.filter_by(user_id=user_id).order_by(Class.name).all()
    if not user_classes or not question_ids:
        return {}
 
    all_states = QuestionUsed.query.filter(
        QuestionUsed.question_id.in_(question_ids)
    ).all()
 
    assigned_map = {}
    for state in all_states:
        assigned_map.setdefault(state.question_id, set()).add(state.class_id)
 
    return {
        qid: [
            {
                "class_id": cls.id,
                "class_name": cls.name,
                "assigned": cls.id in assigned_map.get(qid, set()),
            }
            for cls in user_classes
        ]
        for qid in question_ids
    }

@app.route('/paper/<int:paper_id>/toggle_class/<int:class_id>', methods=['POST'])
@login_required
def toggle_paper_class(paper_id, class_id):
    cls = Class.query.filter_by(id=class_id, user_id=current_user.id).first_or_404()

    existing = PaperUsed.query.filter_by(class_id=class_id, paper_id=paper_id).first()
    if existing:
        db.session.delete(existing)
        flash(f'Removed from "{cls.name}".', 'success')
    else:
        db.session.add(PaperUsed(class_id=class_id, paper_id=paper_id, flagged=False))
        flash(f'Assigned to "{cls.name}".', 'success')

    db.session.commit()

    # Go back to wherever the user came from
    return redirect(request.referrer or url_for('view_paper', paper_id=paper_id))


@app.route('/question/<int:question_id>/toggle_class/<int:class_id>', methods=['POST'])
@login_required
def toggle_question_class(question_id, class_id):
    cls = Class.query.filter_by(id=class_id, user_id=current_user.id).first_or_404()

    existing = QuestionUsed.query.filter_by(class_id=class_id, question_id=question_id).first()
    if existing:
        db.session.delete(existing)
        flash(f'Removed from "{cls.name}".', 'success')
    else:
        db.session.add(QuestionUsed(class_id=class_id, question_id=question_id, flagged=False))
        flash(f'Assigned to "{cls.name}".', 'success')

    db.session.commit()

    # Go back to wherever the user came from
    return redirect(request.referrer or url_for('view_question', question_id=question_id))



def extract_text_from_question(question_id):
    """
    Extract text from a question's PDF using fitz.
    Returns the extracted string, or None if no PDF is attached.
    """
    question = Question.query.get_or_404(question_id)
    if not question.filename:
        return None
 
    qfile = QuestionFile.query.get_or_404(question.filename)
    doc = fitz.open(stream=qfile.data, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc).strip()
    doc.close()
    return text or ""
 
 
# ── Route: extract text for a single question ─────────────────────────────────
 
@app.route('/question/<int:question_id>/extract_text', methods=['POST'])
@login_required
def extract_question_text(question_id):
    question = Question.query.get_or_404(question_id)
    paper = PastPaper.query.get_or_404(question.paper_id)
    if paper.owner_id != current_user.id:
        abort(403)
 
    text = extract_text_from_question(question_id)
 
    if text is None:
        flash("This question has no PDF to extract from.", "error")
        return redirect(url_for('view_question', question_id=question_id))
 
    question.text = text if text else question.text
    db.session.commit()
 
    flash("Text extracted successfully.", "success")
    return redirect(url_for('view_question', question_id=question_id))
 
 
# ── Route: extract text for ALL questions on a paper ──────────────────────────
 
@app.route('/paper/<int:paper_id>/extract_all_text', methods=['POST'])
@login_required
def extract_all_question_text(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    if paper.owner_id != current_user.id:
        abort(403)
 
    updated = 0
    for question in paper.questions:
        if not question.filename:
            continue
        text = extract_text_from_question(question.id)
        if text:
            question.text = text
            updated += 1
 
    db.session.commit()
    flash(f"Extracted text for {updated} question{'s' if updated != 1 else ''}.", "success")
    return redirect(url_for('view_paper', paper_id=paper_id))
 

@app.route('/question/<int:question_id>/llm_process', methods=['POST'])
@login_required
def llm_process_question(question_id):
    question = Question.query.get_or_404(question_id)
    paper = PastPaper.query.get_or_404(question.paper_id)
    if paper.owner_id != current_user.id:
        abort(403)

    if not question.text:
        flash('No text to process — extract text from the PDF first.', 'error')
        return redirect(url_for('view_question', question_id=question_id))

    try:
        cleaned, tags = process_question_with_llm(question.text)
        question.text = cleaned
        question.tags = tags
        db.session.commit()
        flash('Question processed successfully.', 'success')
    except Exception as e:
        flash(f'LLM processing failed: {e}', 'error')

    return redirect(url_for('view_question', question_id=question_id))


@app.route('/paper/<int:paper_id>/llm_process_all', methods=['POST'])
@login_required
def llm_process_all(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    if paper.owner_id != current_user.id:
        abort(403)

    questions_with_text = [
        (q.id, q.text) for q in paper.questions if q.text
    ]

    if not questions_with_text:
        flash('No questions with text to process.', 'error')
        return redirect(url_for('view_paper', paper_id=paper_id))

    # Send all questions in one API call
    try:
        def chunked(lst, size):
            for i in range(0, len(lst), size):
                yield lst[i:i + size]

        results = {}
        for batch in chunked(questions_with_text, 15):
            results.update(process_questions_bulk_with_llm(batch))
    except Exception as e:
        flash(f'LLM processing failed: {e}', 'error')
        return redirect(url_for('view_paper', paper_id=paper_id))

    updated, failed = 0, 0
    for q in paper.questions:
        if q.id in results:
            cleaned, tags = results[q.id]
            if cleaned:
                q.text = cleaned
            q.tags = tags
            updated += 1
        elif q.text:
            failed += 1

    db.session.commit()
    msg = f'Processed {updated} question{"s" if updated != 1 else ""}.'
    if failed:
        msg += f' {failed} failed.'
    flash(msg, 'success' if not failed else 'warning')
    return redirect(url_for('view_paper', paper_id=paper_id))
# --- Main ---
if __name__ == '__main__':

    with app.app_context():
        db.create_all()
    
    app.run(debug=True, port=5001)