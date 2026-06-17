from extensions import db # Import db preventing circular imports
from flask_login import UserMixin # For user authentication

class PastPaper(db.Model):
    """Model for a past paper, which can have multiple questions and is linked to a user."""
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    questions = db.relationship(
        'Question',
        backref='paper',
        lazy=True,
        cascade="all, delete-orphan"
    )
    uploaded_at = db.Column(db.DateTime, default=db.func.now())
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class UserPaper(db.Model):
    """
    Association table linking users to papers in their files,
    allowing for multiple users to have access to the same paper.
    """
    id = db.Column(db.Integer)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, primary_key=True)
    paper_id = db.Column(db.Integer, db.ForeignKey('past_paper.id'), nullable=False, primary_key=True)

class Question(db.Model):
    """
    Model for a question, linked to its parent paper.
    """
    id = db.Column(db.Integer, primary_key=True)
    paper_id = db.Column(db.Integer, db.ForeignKey('past_paper.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=True)
    text = db.Column(db.Text, nullable=True)
    tags = db.Column(db.String(200), nullable=True)

class User(db.Model, UserMixin):
    """Model for a user, which can own papers and have access to multiple classes."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    papers = db.relationship('UserPaper', backref='user', lazy=True)
    classes = db.relationship('Class', backref='user', lazy=True, cascade="all, delete-orphan")
    is_admin = db.Column(db.Boolean, default='False')

class PaperFile(db.Model):
    """Model for storing the actual PDF file data of a past paper."""
    id = db.Column(db.Integer)
    filename = db.Column(db.String(200), nullable=True, index=True, primary_key=True)
    data = db.Column(db.LargeBinary)

class QuestionFile(db.Model):
    """Model for storing the actual PDF file data of a question."""
    id = db.Column(db.Integer)
    filename = db.Column(db.String(200), nullable=True, index=True, primary_key=True)
    data = db.Column(db.LargeBinary)

# Used for tracking a User's class and the papers/questions given them
class Class(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    
    question_states = db.relationship('QuestionUsed', backref='class', lazy=True, cascade="all, delete-orphan")
    paper_states = db.relationship('PaperUsed', backref='class', lazy=True, cascade="all, delete-orphan")

# Used for tracking whether a question has been given to a class
class QuestionUsed(db.Model):
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False, primary_key=True)
    flagged = db.Column(db.Boolean, default=False, nullable=False)

# Used for tracking whether a paper has been given to a class
class PaperUsed(db.Model):
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False, primary_key=True)
    paper_id = db.Column(db.Integer, db.ForeignKey('past_paper.id'), nullable=False, primary_key=True)
    flagged = db.Column(db.Boolean, default=False, nullable=False)