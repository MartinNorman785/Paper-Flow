from extensions import db

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
    filename = db.Column(db.String(200), nullable=True)  # add filename of cropped PDF
    text = db.Column(db.Text, nullable=True)
    tags = db.Column(db.String(200), nullable=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)