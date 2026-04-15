# app.py
from flask import Flask, render_template, current_app, request, redirect, url_for, send_file, send_from_directory, flash, send_from_directory, session, abort
from flask_sqlalchemy import SQLAlchemy
import os
from io import BytesIO
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

from extensions import db
from models import PastPaper, Question, User, PaperFile, QuestionFile

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///papers.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

app.secret_key = os.urandom(24)


@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
    return dict(user=user)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        new_user = User(username=username, password_hash=password)
        db.session.add(new_user)
        db.session.commit()

        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'] = user.id
            flash('You have been registered successfully.', 'success')
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'error')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'] = user.id
            flash('You have been logged in successfully.', 'success')
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'error')
        return render_template('login.html')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged in successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    papers = PastPaper.query.all()
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
                safe_name = secure_filename(file.filename)

                paper = PastPaper(filename=safe_name)
                paperfile = PaperFile(filename=safe_name, data=file.read())

                db.session.add(paper)
                db.session.add(paperfile)

                db.session.commit()
                message = f"Successfully uploaded {safe_name}!"
            else:
                message = "Invalid file type. Only PDFs are allowed."

    return render_template('upload.html', message=message)

@app.route('/question/<int:question_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_question(question_id):
    question = Question.query.get_or_404(question_id)
    if request.method == 'POST':
        question.text = request.form['text']
        question.tags = request.form['tags']
        db.session.commit()
        return redirect(url_for('view_paper', paper_id=question.paper_id))
    return render_template('edit_question.html', question=question)

@app.route('/delete/<int:paper_id>', methods=['POST'])
@login_required
def delete_paper(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    file = PaperFile.query.get_or_404(paper.filename)

    # Delete the database record
    db.session.delete(paper)
    db.session.delete(file)
    db.session.commit()

    flash("Past paper deleted successfully.", "success")
    return redirect(url_for('index'))



@app.route('/question_pdf/<filename>')
@login_required
def question_pdf(filename):
    file = QuestionFile.query.get_or_404(filename)
    return send_file(BytesIO(file.data))

@app.route('/paper/<int:paper_id>')
@login_required
def view_paper(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)

    edit_name = request.args.get('edit_name') == '1'
    return render_template('view_paper.html', paper=paper, edit_name=edit_name)

@app.route('/paper/<int:paper_id>/update_name', methods=['POST'])
@login_required
def update_paper_name(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    file = PaperFile.query.get_or_404(paper.filename)


    new_name = secure_filename(request.form['filename'].strip())

    if new_name:
        if not new_name.lower().endswith('.pdf'):
            new_name += '.pdf'

        file.filename = new_name

        # Update DB
        paper.filename = new_name
        db.session.commit()

        flash("Paper name updated successfully.", "success")

    return redirect(url_for('view_paper', paper_id=paper.id))

@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    paper = PaperFile.query.filter_by(filename=filename).first_or_404()
    return send_file(BytesIO(paper.data), mimetype='application/pdf')

@app.route('/process/<int:paper_id>', methods=['POST'])
@login_required
def process_paper(paper_id):
    from start import process_pdf, get_blocks, split_pdf_by_questions
    from cache import load_blocks, save_blocks

    paper = PastPaper.query.get_or_404(paper_id)
    file_path = paper.filename

    # Load or process blocks
    blocks = load_blocks(paper.filename)
    
    if blocks is None:
        document = process_pdf(paper.filename)
        blocks = get_blocks(paper.filename)
        save_blocks(blocks, paper.filename)

    split_pdf_by_questions(file_path, blocks, paper.id)

    return redirect(url_for('view_paper', paper_id=paper.id))

@app.route('/question/<int:question_id>')
@login_required
def view_question(question_id):
    from models import Question

    question = Question.query.get(question_id)
    if not question:
        abort(404)

    return render_template('view_question.html', question=question)

@app.route('/paper/<int:paper_id>/add_question', methods=['GET', 'POST'])
def add_question(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)
    # TODO

    if request.method == 'POST':
        question_text = request.form.get('question_text', '').strip()
        question_name = request.form.get('question_name', '').strip()

        if not question_text:
            flash("Question text cannot be empty.", "error")
            return redirect(url_for('add_question', paper_id=paper_id))

        # Use text as name if no name provided
        if not question_name:
            question_name = question_text[:30] + "..." if len(question_text) > 30 else question_text

        new_question = Question(
            text=question_text,
            paper_id=paper.id
        )
        db.session.add(new_question)
        db.session.commit()

        flash("Question added successfully!", "success")
        return redirect(url_for('view_paper', paper_id=paper_id))

    return render_template('add_question.html', paper=paper)

@app.route('/delete_question/<int:question_id>', methods=['POST'])
@login_required
def delete_question(question_id):
    question = Question.query.get_or_404(question_id)

    file_path = os.path.join(OUTPUT_DIR, question.filename)

    if os.path.exists(file_path):
        os.remove(file_path)

    db.session.delete(question)
    db.session.commit()

    flash("Deleted", "success")
    # TODO
    return redirect(url_for('view_paper', paper_id=question.paper_id))


@app.route('/delete_questions/<int:paper_id>', methods=['POST'])
@login_required
def delete_questions(paper_id):
    paper = PastPaper.query.get_or_404(paper_id)

    for q in paper.questions:
        if q.filename:
            db.session.delete(QuestionFile.query.get_or_404(q.filename))
        db.session.delete(q)

    db.session.commit()
    flash("All questions deleted.", "success")

    return redirect(url_for('view_paper', paper_id=paper_id))

# --- Main ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5001)