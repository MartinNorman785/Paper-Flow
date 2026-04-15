from extensions import db
from flask_login import UserMixin

class PastPaper(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    questions = db.relationship(
        'Question',
        backref='paper',
        lazy=True,
        cascade="all, delete-orphan"
    )

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    paper_id = db.Column(db.Integer, db.ForeignKey('past_paper.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=True)
    text = db.Column(db.Text, nullable=True)
    tags = db.Column(db.String(200), nullable=True)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class PaperFile(db.Model):
    id = db.Column(db.Integer)
    filename = db.Column(db.String(200), nullable=True, index=True, primary_key=True)
    data = db.Column(db.LargeBinary)

class QuestionFile(db.Model):
    id = db.Column(db.Integer)
    filename = db.Column(db.String(200), nullable=True, index=True, primary_key=True)
    data = db.Column(db.LargeBinary)